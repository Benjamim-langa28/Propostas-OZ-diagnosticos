-- Structured client details, electrical diagnosis services and searchable proposal history.

alter table public.clients
  add column if not exists tax_id text,
  add column if not exists address text,
  add column if not exists contact_name text,
  add column if not exists contact_role text,
  add column if not exists contact_email text;

create index if not exists clients_owner_tax_id_idx
  on public.clients(owner_id, tax_id) where tax_id is not null;

insert into public.services(service_id, category, name, unit, technical_basis, active)
values
  ('ELEC_INSPECT', 'ELECTRICAL_DIAGNOSTIC', 'Inspeção detalhada da rede elétrica', 'serviço', 'Preço e âmbito a validar pelo engenheiro.', true),
  ('ELEC_CONTINUITY', 'ELECTRICAL_TEST', 'Teste de continuidade elétrica', 'ensaio', 'Preço e âmbito a validar pelo engenheiro.', true),
  ('ELEC_INSULATION', 'ELECTRICAL_TEST', 'Teste de resistência de isolamento', 'ensaio', 'Preço e âmbito a validar pelo engenheiro.', true),
  ('ELEC_LOAD', 'ELECTRICAL_TEST', 'Avaliação de carga e sobrecargas', 'ensaio', 'Preço e âmbito a validar pelo engenheiro.', true),
  ('ELEC_REPORT', 'ELECTRICAL_DIAGNOSTIC', 'Relatório técnico de diagnóstico elétrico', 'relatório', 'Preço e âmbito a validar pelo engenheiro.', true)
on conflict (service_id) do nothing;

create table if not exists public.proposal_library (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text not null,
  client_name text,
  project_type text,
  location text,
  proposal_no text,
  file_name text not null,
  mime_type text,
  storage_path text not null,
  summary text not null default '',
  extracted_text text not null default '',
  tags text[] not null default '{}',
  search_document tsvector generated always as (
    setweight(to_tsvector('portuguese', coalesce(title, '') || ' ' || coalesce(client_name, '') || ' ' ||
      coalesce(project_type, '') || ' ' || coalesce(location, '') || ' ' || coalesce(summary, '') || ' ' ||
      coalesce(extracted_text, '')), 'A')
  ) stored,
  created_at timestamptz not null default now()
);

create index if not exists proposal_library_owner_created_idx
  on public.proposal_library(owner_id, created_at desc);
create index if not exists proposal_library_search_idx
  on public.proposal_library using gin(search_document);

alter table public.proposal_library enable row level security;
drop policy if exists "owners manage proposal library records" on public.proposal_library;
create policy "owners manage proposal library records" on public.proposal_library
  for all to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));
grant select, insert, update, delete on public.proposal_library to authenticated;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values (
  'proposal-library', 'proposal-library', false, 15728640,
  array['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'text/plain', 'text/csv', 'message/rfc822']
)
on conflict (id) do update set public = false, file_size_limit = 15728640,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "owners manage their proposal reference uploads" on storage.objects;
create policy "owners manage their proposal reference uploads" on storage.objects for all to authenticated
  using (bucket_id = 'proposal-library' and (storage.foldername(name))[1] = (select auth.uid()::text))
  with check (bucket_id = 'proposal-library' and (storage.foldername(name))[1] = (select auth.uid()::text));

create or replace function public.search_proposal_references(p_query text default '', p_limit integer default 8)
returns table (
  source text,
  id uuid,
  request_id uuid,
  proposal_no text,
  title text,
  client_name text,
  location text,
  summary text,
  file_name text,
  storage_path text,
  created_at timestamptz,
  match_score real
)
language sql
stable
security invoker
set search_path = public, auth, pg_catalog
as $$
  with search_input as (
    select nullif(trim(coalesce(p_query, '')), '') as query_text,
           websearch_to_tsquery('portuguese'::regconfig, coalesce(nullif(trim(p_query), ''), '')) as query
  ),
  uploaded as (
    select 'uploaded'::text as source, library.id, null::uuid as request_id,
           library.proposal_no, library.title, library.client_name, library.location,
           left(coalesce(nullif(library.summary, ''), library.extracted_text), 800) as summary,
           library.file_name, library.storage_path, library.created_at,
           case when search_input.query_text is null then 0::real
                else ts_rank(library.search_document, search_input.query) end as match_score
    from public.proposal_library as library
    cross join search_input
    where library.owner_id = auth.uid()
      and (search_input.query_text is null
           or library.search_document @@ search_input.query
           or library.title ilike '%' || search_input.query_text || '%'
           or library.extracted_text ilike '%' || search_input.query_text || '%')
  ),
  generated as (
    select 'generated'::text as source, proposal.id, request.id as request_id,
           proposal.proposal_no, request.title,
           request.extracted_fields ->> 'client_name' as client_name,
           request.extracted_fields ->> 'location' as location,
           left(coalesce(nullif(string_agg(distinct item.name, ' · ' order by item.name), ''),
                         request.extracted_fields ->> 'objective', request.raw_text), 800) as summary,
           null::text as file_name, null::text as storage_path, proposal.created_at,
           case when search_input.query_text is null then 0::real
                else ts_rank(
                  to_tsvector('portuguese'::regconfig, concat_ws(' ', request.title, request.raw_text,
                    request.extracted_fields ->> 'client_name', request.extracted_fields ->> 'project_name',
                    request.extracted_fields ->> 'objective', request.extracted_fields ->> 'requested_services',
                    request.extracted_fields ->> 'categories')),
                  search_input.query
                ) end as match_score
    from public.proposals as proposal
    join public.proposal_requests as request on request.id = proposal.request_id
    left join public.proposal_items as item on item.proposal_id = proposal.id and item.enabled
    cross join search_input
    where proposal.owner_id = auth.uid()
      and (search_input.query_text is null
           or to_tsvector('portuguese'::regconfig, concat_ws(' ', request.title, request.raw_text,
                request.extracted_fields ->> 'client_name', request.extracted_fields ->> 'project_name',
                request.extracted_fields ->> 'objective', request.extracted_fields ->> 'requested_services',
                request.extracted_fields ->> 'categories')) @@ search_input.query
           or request.title ilike '%' || search_input.query_text || '%'
           or request.raw_text ilike '%' || search_input.query_text || '%')
    group by proposal.id, request.id, request.title, request.raw_text, request.extracted_fields,
             proposal.proposal_no, proposal.created_at, search_input.query_text, search_input.query
  )
  select * from (
    select * from uploaded
    union all
    select * from generated
  ) as matches
  order by match_score desc, created_at desc
  limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

revoke all on function public.search_proposal_references(text, integer) from public, anon;
grant execute on function public.search_proposal_references(text, integer) to authenticated;
