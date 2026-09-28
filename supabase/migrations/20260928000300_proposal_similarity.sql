-- Enrich searchable reference text so the API can score similarity across
-- generated proposals and uploaded proposal documents.

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
           left(concat_ws(' · ', nullif(library.project_type, ''),
             nullif(array_to_string(library.tags, ' · '), ''),
             nullif(library.summary, ''), nullif(library.extracted_text, '')), 1000) as summary,
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
           left(concat_ws(' · ',
             nullif(string_agg(distinct item.name, ' · ' order by item.name), ''),
             nullif(request.extracted_fields ->> 'objective', ''),
             nullif(request.extracted_fields ->> 'requested_services', ''),
             nullif(request.extracted_fields ->> 'categories', ''),
             left(coalesce(request.raw_text, ''), 400)), 1000) as summary,
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
