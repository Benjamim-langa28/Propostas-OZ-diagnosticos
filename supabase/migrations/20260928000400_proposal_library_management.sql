-- Support explicit request cancellation and a richer, owner-scoped proposal catalog.

alter type public.proposal_status add value if not exists 'CANCELLED';

create index if not exists proposals_owner_proposal_no_idx
  on public.proposals(owner_id, proposal_no);
create index if not exists proposal_library_owner_proposal_no_idx
  on public.proposal_library(owner_id, proposal_no);

create or replace function public.list_proposal_library(p_query text default '', p_limit integer default 100)
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
  match_score real,
  status text,
  project_name text,
  objective text,
  total numeric
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
           left(concat_ws(' · ', nullif(library.project_type, ''),
             nullif(array_to_string(library.tags, ' · '), ''),
             nullif(library.summary, ''), nullif(library.extracted_text, '')), 1000) as summary,
           library.file_name, library.storage_path, library.created_at, 0::real as match_score,
           null::text as status, null::text as project_name,
           library.project_type as objective, null::numeric as total
    from public.proposal_library as library
    cross join search_input
    where library.owner_id = auth.uid()
      and (search_input.query_text is null
           or library.search_document @@ search_input.query
           or concat_ws(' ', library.proposal_no, library.title, library.client_name,
                library.location, library.project_type, array_to_string(library.tags, ' '),
                library.extracted_text) ilike '%' || search_input.query_text || '%')
  ),
  generated as (
    select 'generated'::text as source, proposal.id, request.id as request_id,
           proposal.proposal_no,
           coalesce(nullif(request.extracted_fields ->> 'project_name', ''), request.title) as title,
           request.extracted_fields ->> 'client_name' as client_name,
           request.extracted_fields ->> 'location' as location,
           left(concat_ws(' · ',
             nullif(string_agg(distinct item.name, ' · ' order by item.name)
               filter (where item.enabled), ''),
             nullif(request.extracted_fields ->> 'objective', ''),
             nullif(request.extracted_fields ->> 'requested_services', ''),
             nullif(request.extracted_fields ->> 'categories', ''),
             left(coalesce(request.raw_text, ''), 400)), 1000) as summary,
           null::text as file_name, null::text as storage_path, proposal.created_at,
           0::real as match_score, proposal.status::text as status,
           request.extracted_fields ->> 'project_name' as project_name,
           request.extracted_fields ->> 'objective' as objective,
           (coalesce(sum(item.quantity * item.unit_price) filter (where item.enabled), 0)
             * (1 + proposal.vat_rate / 100.0))::numeric as total
    from public.proposals as proposal
    join public.proposal_requests as request on request.id = proposal.request_id
    left join public.proposal_items as item on item.proposal_id = proposal.id
    cross join search_input
    where proposal.owner_id = auth.uid()
      and (search_input.query_text is null
           or to_tsvector('portuguese'::regconfig, concat_ws(' ', proposal.proposal_no,
                request.title, request.raw_text, request.extracted_fields ->> 'client_name',
                request.extracted_fields ->> 'project_name', request.extracted_fields ->> 'location',
                request.extracted_fields ->> 'objective', request.extracted_fields ->> 'requested_services',
                request.extracted_fields ->> 'categories')) @@ search_input.query
           or concat_ws(' ', proposal.proposal_no, request.title, request.raw_text,
                request.extracted_fields ->> 'client_name', request.extracted_fields ->> 'project_name',
                request.extracted_fields ->> 'location', request.extracted_fields ->> 'objective')
                ilike '%' || search_input.query_text || '%'
           or item.name ilike '%' || search_input.query_text || '%')
    group by proposal.id, request.id, request.title, request.raw_text, request.extracted_fields,
             proposal.proposal_no, proposal.created_at, proposal.status, proposal.vat_rate,
             search_input.query_text, search_input.query
  )
  select * from (
    select * from uploaded
    union all
    select * from generated
  ) as catalog_rows
  order by catalog_rows.created_at desc, catalog_rows.proposal_no nulls last
  limit greatest(1, least(coalesce(p_limit, 100), 500));
$$;

revoke all on function public.list_proposal_library(text, integer) from public, anon;
grant execute on function public.list_proposal_library(text, integer) to authenticated;
