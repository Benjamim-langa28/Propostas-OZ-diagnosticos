-- RAG technical knowledge: documents, chunks, embeddings, links to the kb_* catalogue and hybrid search.
--
-- Design rules (see docs/AI_ARCHITECTURE.md):
--   * The kb_* catalogue stays the single source of technical codes; chunks only LINK to those codes.
--   * Every chunk keeps its origin (document, pages, process number) so answers can cite a source.
--   * Client identity lives only on kb_documents and is never part of the indexed chunk text.
--   * Numbers/prices are never stored here: the pricing engine owns them.
--   * Knowledge is company-wide for ADMIN/MANAGER/ENGINEER (unlike the per-owner request tables).

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Access helpers (reuse public.my_role() from the initial schema)
-- ---------------------------------------------------------------------------
create or replace function public.kb_has_access()
returns boolean language sql stable
as $$ select coalesce(public.my_role() in ('ADMIN', 'MANAGER', 'ENGINEER'), false) $$;

create or replace function public.kb_is_manager()
returns boolean language sql stable
as $$ select coalesce(public.my_role() in ('ADMIN', 'MANAGER'), false) $$;

-- ---------------------------------------------------------------------------
-- Documents
-- ---------------------------------------------------------------------------
create table if not exists public.kb_documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  storage_path text not null,
  file_name text not null,
  mime_type text,
  sha256 text not null unique,                       -- prevents indexing the same file twice
  doc_type text not null check (doc_type in ('relatorio', 'proposta', 'procedimento', 'norma', 'ficha')),
  title text not null,
  process_number text,                               -- internal process number (e.g. 2987)
  project_type text,                                 -- type of works/structure
  client_name text,                                  -- internal only; never copied into chunks
  doc_date date,
  confidential boolean not null default true,
  ocr boolean not null default false,                -- text came from OCR: lower confidence
  status text not null default 'pending' check (status in ('pending', 'processing', 'indexed', 'failed')),
  error text,
  page_count integer,
  chunk_count integer not null default 0,
  embedding_model text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists kb_documents_type_status_idx on public.kb_documents(doc_type, status);
create index if not exists kb_documents_process_idx on public.kb_documents(process_number) where process_number is not null;
create index if not exists kb_documents_owner_idx on public.kb_documents(owner_id, created_at desc);

drop trigger if exists kb_documents_set_updated_at on public.kb_documents;
create trigger kb_documents_set_updated_at before update on public.kb_documents
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Chunks
-- ---------------------------------------------------------------------------
create table if not exists public.kb_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.kb_documents(id) on delete cascade,
  chunk_index integer not null,
  section_type text not null default 'outro' check (section_type in (
    'identificacao', 'escopo', 'patologia', 'causa', 'resolucao',
    'ensaio', 'procedimento', 'conclusao', 'outro'
  )),
  page_from integer,
  page_to integer,
  content text not null check (length(btrim(content)) > 0),
  token_count integer,
  embedding vector(1536),                            -- null until embedded (text-embedding-3-small size)
  embedding_model text,                              -- lets us re-embed when the model changes
  search_document tsvector generated always as (to_tsvector('portuguese', content)) stored,
  reviewed boolean not null default false,           -- validated by an engineer
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (document_id, chunk_index)
);

create index if not exists kb_chunks_document_idx on public.kb_chunks(document_id);
create index if not exists kb_chunks_fts_idx on public.kb_chunks using gin(search_document);
create index if not exists kb_chunks_embedding_idx on public.kb_chunks
  using hnsw (embedding vector_cosine_ops) with (m = 16, ef_construction = 64);
create index if not exists kb_chunks_pending_embedding_idx on public.kb_chunks(created_at) where embedding is null;

-- ---------------------------------------------------------------------------
-- Chunk <-> catalogue codes (only codes that exist in kb_* can be linked)
-- ---------------------------------------------------------------------------
create table if not exists public.kb_chunk_codes (
  chunk_id uuid not null references public.kb_chunks(id) on delete cascade,
  code_type text not null check (code_type in ('pathology', 'cause', 'test', 'solution')),
  code text not null,
  suggested_by text not null default 'rule' check (suggested_by in ('rule', 'llm', 'engineer')),
  confirmed boolean not null default false,
  confirmed_by uuid references auth.users(id) on delete set null,
  confirmed_at timestamptz,
  primary key (chunk_id, code_type, code)
);

create index if not exists kb_chunk_codes_lookup_idx on public.kb_chunk_codes(code_type, code);

create or replace function public.kb_chunk_codes_validate()
returns trigger language plpgsql set search_path = public
as $$
declare
  v_exists boolean;
begin
  v_exists := case new.code_type
    when 'pathology' then exists (select 1 from public.kb_pathologies where code = new.code)
    when 'cause'     then exists (select 1 from public.kb_causes where code = new.code)
    when 'test'      then exists (select 1 from public.kb_tests where code = new.code)
    when 'solution'  then exists (select 1 from public.kb_solutions where code = new.code)
    else false
  end;
  if not v_exists then
    raise exception 'Unknown % code: %', new.code_type, new.code using errcode = '23503';
  end if;
  return new;
end;
$$;

drop trigger if exists kb_chunk_codes_validate_trg on public.kb_chunk_codes;
create trigger kb_chunk_codes_validate_trg before insert or update of code_type, code on public.kb_chunk_codes
  for each row execute function public.kb_chunk_codes_validate();

-- ---------------------------------------------------------------------------
-- Evaluation set: real past requests with the known correct outcome (recall@k checks)
-- ---------------------------------------------------------------------------
create table if not exists public.kb_eval_cases (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  query text not null,
  expected_process_numbers text[] not null default '{}',
  expected_codes jsonb not null default '[]'::jsonb,   -- e.g. [{"code_type":"test","code":"T012"}]
  notes text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.kb_documents enable row level security;
alter table public.kb_chunks enable row level security;
alter table public.kb_chunk_codes enable row level security;
alter table public.kb_eval_cases enable row level security;

drop policy if exists "kb staff read documents" on public.kb_documents;
create policy "kb staff read documents" on public.kb_documents
  for select to authenticated using ((select public.kb_has_access()));

drop policy if exists "kb staff add documents" on public.kb_documents;
create policy "kb staff add documents" on public.kb_documents
  for insert to authenticated
  with check (owner_id = (select auth.uid()) and (select public.kb_has_access()));

drop policy if exists "kb owner or manager updates documents" on public.kb_documents;
create policy "kb owner or manager updates documents" on public.kb_documents
  for update to authenticated
  using ((owner_id = (select auth.uid()) and (select public.kb_has_access())) or (select public.kb_is_manager()))
  with check ((owner_id = (select auth.uid()) and (select public.kb_has_access())) or (select public.kb_is_manager()));

drop policy if exists "kb owner or manager deletes documents" on public.kb_documents;
create policy "kb owner or manager deletes documents" on public.kb_documents
  for delete to authenticated
  using ((owner_id = (select auth.uid()) and (select public.kb_has_access())) or (select public.kb_is_manager()));

drop policy if exists "kb staff read chunks" on public.kb_chunks;
create policy "kb staff read chunks" on public.kb_chunks
  for select to authenticated using ((select public.kb_has_access()));

drop policy if exists "kb document owner or manager writes chunks" on public.kb_chunks;
create policy "kb document owner or manager writes chunks" on public.kb_chunks
  for all to authenticated
  using (exists (
    select 1 from public.kb_documents d
    where d.id = kb_chunks.document_id
      and ((d.owner_id = (select auth.uid()) and (select public.kb_has_access())) or (select public.kb_is_manager()))
  ))
  with check (exists (
    select 1 from public.kb_documents d
    where d.id = kb_chunks.document_id
      and ((d.owner_id = (select auth.uid()) and (select public.kb_has_access())) or (select public.kb_is_manager()))
  ));

drop policy if exists "kb staff read chunk codes" on public.kb_chunk_codes;
create policy "kb staff read chunk codes" on public.kb_chunk_codes
  for select to authenticated using ((select public.kb_has_access()));

-- Any engineer may confirm/adjust code links (that is the validation step); documents' owners ingest them.
drop policy if exists "kb staff write chunk codes" on public.kb_chunk_codes;
create policy "kb staff write chunk codes" on public.kb_chunk_codes
  for all to authenticated
  using ((select public.kb_has_access()))
  with check ((select public.kb_has_access()));

drop policy if exists "kb staff manage eval cases" on public.kb_eval_cases;
create policy "kb staff manage eval cases" on public.kb_eval_cases
  for all to authenticated
  using ((select public.kb_has_access()))
  with check (owner_id = (select auth.uid()) and (select public.kb_has_access()));

revoke all on public.kb_documents, public.kb_chunks, public.kb_chunk_codes, public.kb_eval_cases from anon, public;
grant select, insert, update, delete on public.kb_documents, public.kb_chunks,
  public.kb_chunk_codes, public.kb_eval_cases to authenticated;
revoke all on function public.kb_has_access(), public.kb_is_manager() from public, anon;
grant execute on function public.kb_has_access(), public.kb_is_manager() to authenticated;

-- ---------------------------------------------------------------------------
-- Private storage bucket for the original files (path: <user id>/<file>)
-- ---------------------------------------------------------------------------
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values (
  'kb-documents', 'kb-documents', false, 52428800,
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain'
  ]
)
on conflict (id) do update
set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "kb staff read knowledge files" on storage.objects;
create policy "kb staff read knowledge files" on storage.objects for select to authenticated
  using (bucket_id = 'kb-documents' and (select public.kb_has_access()));

drop policy if exists "kb staff upload knowledge files" on storage.objects;
create policy "kb staff upload knowledge files" on storage.objects for insert to authenticated
  with check (
    bucket_id = 'kb-documents'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
    and (select public.kb_has_access())
  );

drop policy if exists "kb owner or manager deletes knowledge files" on storage.objects;
create policy "kb owner or manager deletes knowledge files" on storage.objects for delete to authenticated
  using (
    bucket_id = 'kb-documents'
    and (
      ((storage.foldername(name))[1] = (select auth.uid()::text) and (select public.kb_has_access()))
      or (select public.kb_is_manager())
    )
  );

-- ---------------------------------------------------------------------------
-- Hybrid search: full-text (Portuguese) + vector similarity, fused with RRF (k = 60).
--   * Runs as the caller (security invoker), so RLS applies.
--   * p_embedding may be null (no OpenAI key): falls back to full-text only.
--   * Hard filters run first: document types and catalogue codes already found by the diagnosis step.
--   * Returns both raw signals so the API can apply its own "no match" threshold.
--   * Client identity is deliberately not returned.
-- ---------------------------------------------------------------------------
create or replace function public.kb_search(
  p_query text,
  p_embedding vector(1536) default null,
  p_limit integer default 8,
  p_doc_types text[] default null,
  p_code_type text default null,
  p_codes text[] default null,
  p_confirmed_codes_only boolean default false,
  p_reviewed_only boolean default false,
  p_min_similarity real default 0.30
)
returns table (
  chunk_id uuid,
  document_id uuid,
  process_number text,
  doc_type text,
  section_type text,
  page_from integer,
  page_to integer,
  content text,
  ocr boolean,
  similarity real,
  text_rank real,
  score real
)
language sql stable security invoker
set search_path = public, extensions, pg_temp
as $$
  with q as (
    select case when nullif(btrim(p_query), '') is null then null
                else websearch_to_tsquery('portuguese', p_query) end as tsq
  ),
  eligible as not materialized (
    select c.id, c.document_id, c.section_type, c.page_from, c.page_to, c.content,
           c.embedding, c.search_document, d.process_number, d.doc_type, d.ocr
    from public.kb_chunks c
    join public.kb_documents d on d.id = c.document_id
    where d.status = 'indexed'
      and (p_doc_types is null or d.doc_type = any(p_doc_types))
      and (not p_reviewed_only or c.reviewed)
      and (
        p_codes is null
        or exists (
          select 1 from public.kb_chunk_codes cc
          where cc.chunk_id = c.id
            and cc.code = any(p_codes)
            and (p_code_type is null or cc.code_type = p_code_type)
            and (not p_confirmed_codes_only or cc.confirmed)
        )
      )
  ),
  fts as (
    select s.id, s.rank, row_number() over (order by s.rank desc) as rnk
    from (
      select e.id, ts_rank_cd(e.search_document, q.tsq) as rank
      from eligible e cross join q
      where q.tsq is not null and e.search_document @@ q.tsq
      order by rank desc
      limit 20
    ) s
  ),
  vec as (
    select s.id, s.sim, row_number() over (order by s.sim desc) as rnk
    from (
      select e.id, (1 - (e.embedding <=> p_embedding)) as sim
      from eligible e
      where p_embedding is not null
        and e.embedding is not null
        and (1 - (e.embedding <=> p_embedding)) >= p_min_similarity
      order by e.embedding <=> p_embedding
      limit 20
    ) s
  )
  select e.id, e.document_id, e.process_number, e.doc_type, e.section_type,
         e.page_from, e.page_to, e.content, e.ocr,
         v.sim::real, f.rank::real,
         (coalesce(1.0 / (60 + f.rnk), 0) + coalesce(1.0 / (60 + v.rnk), 0))::real as score
  from eligible e
  left join fts f on f.id = e.id
  left join vec v on v.id = e.id
  where f.id is not null or v.id is not null
  order by score desc
  limit least(greatest(coalesce(p_limit, 8), 1), 50)
$$;

revoke all on function public.kb_search(text, vector, integer, text[], text, text[], boolean, boolean, real) from public, anon;
grant execute on function public.kb_search(text, vector, integer, text[], text, text[], boolean, boolean, real) to authenticated;
