-- OZ Intelligent Proposal — clean initial schema for a new Supabase project.
create extension if not exists pgcrypto;

do $$ begin
  create type public.app_role as enum ('ADMIN', 'MANAGER', 'ENGINEER', 'COMMERCIAL', 'VIEWER');
exception when duplicate_object then null;
end $$;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null default '',
  role public.app_role not null default 'ENGINEER',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.create_profile_for_new_user()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
  insert into public.profiles(id, full_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), ''))
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created_profile
after insert on auth.users
for each row execute function public.create_profile_for_new_user();

create or replace function public.set_updated_at()
returns trigger language plpgsql set search_path = public
as $$ begin new.updated_at = now(); return new; end $$;

create or replace function public.my_role()
returns public.app_role language sql stable security definer set search_path = public
as $$ select role from public.profiles where id = auth.uid() $$;

create table public.clients (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null,
  email text,
  phone text,
  organization text,
  payment_terms text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  client_id uuid references public.clients(id) on delete set null,
  name text not null,
  location text,
  year_built integer,
  building_type text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create type public.proposal_status as enum (
  'DRAFT', 'ANALYSING', 'NEEDS_INFORMATION', 'TECHNICAL_SCOPE', 'PRICING',
  'TECHNICAL_REVIEW', 'READY_FOR_APPROVAL', 'APPROVED', 'GENERATED', 'SENT',
  'CLIENT_REVIEW', 'ACCEPTED', 'REJECTED', 'EXPIRED'
);

create table public.proposal_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  client_id uuid references public.clients(id) on delete set null,
  project_id uuid references public.projects(id) on delete set null,
  title text not null,
  source text not null default 'manual' check (source in ('manual', 'email', 'upload', 'chat')),
  raw_text text not null default '',
  extracted_fields jsonb not null default '{}'::jsonb,
  received_at timestamptz not null default now(),
  deadline date,
  status public.proposal_status not null default 'DRAFT',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.proposal_analysis (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  request_id uuid not null unique references public.proposal_requests(id) on delete cascade,
  categories text[] not null default '{}',
  extracted jsonb not null default '{}'::jsonb,
  missing_information text[] not null default '{}',
  restrictions text[] not null default '{}',
  analysis_mode text not null default 'RULES' check (analysis_mode in ('OPENAI', 'RULES')),
  created_at timestamptz not null default now()
);

create table public.services (
  service_id text primary key,
  category text not null,
  name text not null,
  unit text not null default 'un',
  base_cost numeric(12,2) not null default 0,
  selling_price numeric(12,2) not null default 0,
  technical_hours numeric(7,2) not null default 0,
  equipment_cost numeric(12,2) not null default 0,
  laboratory_cost numeric(12,2) not null default 0,
  travel_cost numeric(12,2) not null default 0,
  technical_basis text,
  active boolean not null default true,
  version integer not null default 1
);

create table public.proposals (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  request_id uuid not null unique references public.proposal_requests(id) on delete cascade,
  proposal_no text not null unique,
  status public.proposal_status not null default 'DRAFT',
  vat_rate numeric(5,2) not null default 23 check (vat_rate between 0 and 100),
  validity_days integer not null default 30 check (validity_days > 0),
  execution_period text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.mqt_items (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  request_id uuid not null references public.proposal_requests(id) on delete cascade,
  code text,
  description text not null,
  unit text not null default 'un',
  quantity numeric(12,3) not null default 0 check (quantity >= 0),
  service_id text references public.services(service_id) on delete set null,
  origin text not null default 'REQUIRES_REVIEW' check (origin in ('EXTRACTED','UNKNOWN','INFERRED','SUGGESTED','VALIDATED','REQUIRES_REVIEW')),
  created_at timestamptz not null default now()
);

create table public.proposal_items (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  proposal_id uuid not null references public.proposals(id) on delete cascade,
  service_id text references public.services(service_id) on delete set null,
  name text not null,
  unit text not null default 'un',
  is_optional boolean not null default false,
  enabled boolean not null default true,
  quantity numeric(12,3) not null default 1 check (quantity >= 0),
  unit_price numeric(12,2) not null default 0 check (unit_price >= 0),
  origin text not null default 'SUGGESTED' check (origin in ('EXTRACTED','UNKNOWN','INFERRED','SUGGESTED','VALIDATED','REQUIRES_REVIEW')),
  source_mqt_item_id uuid unique references public.mqt_items(id) on delete set null,
  technical_basis text,
  position integer not null default 0,
  created_at timestamptz not null default now()
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  request_id uuid not null references public.proposal_requests(id) on delete cascade,
  file_name text not null,
  mime_type text,
  storage_path text,
  extracted_text text not null default '',
  created_at timestamptz not null default now()
);

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('proposal-documents', 'proposal-documents', false, 15728640,
  array['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'text/plain', 'text/csv', 'message/rfc822'])
on conflict (id) do update set public = false, file_size_limit = 15728640,
  allowed_mime_types = excluded.allowed_mime_types;

create policy "users manage their own proposal uploads" on storage.objects for all to authenticated
using (bucket_id = 'proposal-documents' and (storage.foldername(name))[1] = (select auth.uid()::text))
with check (bucket_id = 'proposal-documents' and (storage.foldername(name))[1] = (select auth.uid()::text));

create table public.visits (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  request_id uuid not null references public.proposal_requests(id) on delete cascade,
  scheduled_at timestamptz not null,
  note text not null default '',
  status text not null default 'SCHEDULED' check (status in ('SCHEDULED', 'COMPLETED', 'CANCELLED')),
  created_at timestamptz not null default now()
);

create table public.proposal_versions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  proposal_id uuid not null references public.proposals(id) on delete cascade,
  version integer not null,
  snapshot jsonb not null,
  pdf_path text,
  created_at timestamptz not null default now(),
  unique (proposal_id, version)
);

create table public.proposal_counters (
  name text primary key,
  value bigint not null default 0
);
insert into public.proposal_counters(name, value) values ('proposal', 0);

create or replace function public.create_proposal_for_request(p_request_id uuid)
returns table(proposal_id uuid, proposal_no text)
language plpgsql security definer set search_path = public, auth
as $$
declare
  v_owner uuid := auth.uid();
  v_request public.proposal_requests%rowtype;
  v_number bigint;
  v_proposal_id uuid;
  v_proposal_no text;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  select * into v_request from public.proposal_requests
    where id = p_request_id and owner_id = v_owner for update;
  if not found then raise exception 'Request not found'; end if;
  if coalesce(v_request.extracted_fields->'missing_information', '[]'::jsonb) <> '[]'::jsonb then
    raise exception 'Request needs more information before proposal generation';
  end if;

  select p.id, p.proposal_no into v_proposal_id, v_proposal_no
    from public.proposals p where p.request_id = p_request_id and p.owner_id = v_owner;
  if found then return query select v_proposal_id, v_proposal_no; return; end if;

  update public.proposal_counters set value = value + 1 where name = 'proposal' returning value into v_number;
  v_proposal_no := 'OZ-' || to_char(current_date, 'YYYY') || '-' || lpad(v_number::text, 4, '0');
  insert into public.proposals(owner_id, request_id, proposal_no, status)
    values (v_owner, p_request_id, v_proposal_no, 'DRAFT') returning id into v_proposal_id;
  update public.proposal_requests set status = 'TECHNICAL_SCOPE', updated_at = now() where id = p_request_id;
  return query select v_proposal_id, v_proposal_no;
end;
$$;
revoke all on function public.create_proposal_for_request(uuid) from public, anon;
grant execute on function public.create_proposal_for_request(uuid) to authenticated;

create or replace function public.save_proposal_version(p_proposal_id uuid)
returns table(version_id uuid, version_number integer)
language plpgsql security definer set search_path = public, auth
as $$
declare
  v_owner uuid := auth.uid();
  v_proposal public.proposals%rowtype;
  v_request public.proposal_requests%rowtype;
  v_version integer;
  v_id uuid;
  v_items jsonb;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  select * into v_proposal from public.proposals
    where id = p_proposal_id and owner_id = v_owner for update;
  if not found then raise exception 'Proposal not found'; end if;
  select * into v_request from public.proposal_requests where id = v_proposal.request_id;
  select coalesce(jsonb_agg(to_jsonb(i) order by i.position, i.created_at), '[]'::jsonb)
    into v_items from public.proposal_items i where i.proposal_id = p_proposal_id and i.owner_id = v_owner;
  select coalesce(max(pv.version), 0) + 1 into v_version
    from public.proposal_versions pv where pv.proposal_id = p_proposal_id;
  insert into public.proposal_versions(owner_id, proposal_id, version, snapshot)
    values (v_owner, p_proposal_id, v_version,
      jsonb_build_object('proposal', to_jsonb(v_proposal), 'request', to_jsonb(v_request), 'items', v_items))
    returning id into v_id;
  return query select v_id, v_version;
end;
$$;
revoke all on function public.save_proposal_version(uuid) from public, anon;
grant execute on function public.save_proposal_version(uuid) to authenticated;

create table public.audit_logs (
  id bigint generated always as identity primary key,
  user_id uuid,
  table_name text not null,
  row_id text not null,
  action text not null,
  old_data jsonb,
  new_data jsonb,
  created_at timestamptz not null default now()
);

create or replace function public.audit_proposal_change()
returns trigger language plpgsql security definer set search_path = public, auth
as $$
declare v_row jsonb; v_old jsonb; v_new jsonb;
begin
  if tg_op <> 'INSERT' then v_old := to_jsonb(old); end if;
  if tg_op <> 'DELETE' then v_new := to_jsonb(new); end if;
  v_row := coalesce(v_new, v_old);
  insert into public.audit_logs(user_id, table_name, row_id, action, old_data, new_data)
  values (auth.uid(), tg_table_name, v_row->>'id', tg_op, v_old, v_new);
  return coalesce(new, old);
end;
$$;
create trigger audit_proposals after insert or update or delete on public.proposals
  for each row execute function public.audit_proposal_change();
create trigger audit_proposal_items after insert or update or delete on public.proposal_items
  for each row execute function public.audit_proposal_change();

do $$
declare t text;
begin
  foreach t in array array['clients','projects','proposal_requests','proposal_analysis','proposals','mqt_items','proposal_items','documents','visits','proposal_versions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy "owner manages own rows" on public.%I for all to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()))', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
  end loop;
end $$;

alter table public.profiles enable row level security;
create policy "profile owner can read" on public.profiles for select to authenticated using (id = (select auth.uid()));
grant select on public.profiles to authenticated;

alter table public.services enable row level security;
create policy "authenticated users read active services" on public.services for select to authenticated using (active);
grant select on public.services to authenticated;

alter table public.proposal_counters enable row level security;
revoke all on public.proposal_counters from anon, authenticated;

alter table public.audit_logs enable row level security;
create policy "users read own audit events" on public.audit_logs for select to authenticated using (user_id = (select auth.uid()));
grant select on public.audit_logs to authenticated;

create index proposal_requests_owner_created_idx on public.proposal_requests(owner_id, created_at desc);
create index proposal_requests_owner_status_idx on public.proposal_requests(owner_id, status);
create index proposals_owner_created_idx on public.proposals(owner_id, created_at desc);
create index proposal_items_proposal_position_idx on public.proposal_items(proposal_id, position);
create index mqt_items_request_idx on public.mqt_items(request_id);
create index documents_request_idx on public.documents(request_id);
create index visits_request_schedule_idx on public.visits(request_id, scheduled_at);

create trigger clients_updated_at before update on public.clients for each row execute function public.set_updated_at();
create trigger projects_updated_at before update on public.projects for each row execute function public.set_updated_at();
create trigger requests_updated_at before update on public.proposal_requests for each row execute function public.set_updated_at();
create trigger proposals_updated_at before update on public.proposals for each row execute function public.set_updated_at();

insert into public.services(service_id, category, name, unit, selling_price, technical_basis) values
  ('EST_VISUAL','BUILDING_PATHOLOGY','Estudo preliminar com inspeção visual (inclui relatório)','un',2900,'Inspeção visual e relatório preliminar'),
  ('MOB','SURVEY','Verba fixa de mobilização','un',900,null),
  ('PACO','NDT','Pacometria','zona',150,'Deteção de armaduras'),
  ('CARB','NDT','Carbonatação','ponto',40,'Ensaio colorimétrico'),
  ('CLOR','NDT','Teor de cloretos','zona',120,'Amostragem por 3 profundidades'),
  ('CAROTE','NDT','Resistência dos betões (carotes)','un',220,'Carotes Ø75mm conforme NP EN 12504-1:2003'),
  ('REL_ENS','NDT','Relatório de ensaios','un',1400,null),
  ('FISS_M1','MONITORING','Modalidade 1 — fornecer/instalar 12 fissurómetros','un',1000,'Situação de referência'),
  ('FISS_M2','MONITORING','Modalidade 2 — fornecer/instalar + 4 leituras mensais','un',3800,'Leituras periódicas'),
  ('VERBA_LEV','SURVEY','Verba fixa (mobilização, acessos, energia)','un',1900,null),
  ('INSP_ANOM','SURVEY','Inspeção visual — levantamento de anomalias','un',3200,null),
  ('LEV_ANOM','SURVEY','Levantamento de anomalias (complementar)','un',1000,null),
  ('MACACO','NDT','Macacos planos duplos','un',900,null),
  ('RESIST','NDT','Resistografia (madeira)','un',50,null),
  ('REL_FINAL','SURVEY','Relatório final (CAD + fotografia)','un',1900,null),
  ('VIST_ENV','MONITORING','Vistoria inicial das construções da envolvente + relatório de referência','un',0,'Preço a definir pelo engenheiro')
on conflict (service_id) do update set category=excluded.category, name=excluded.name, unit=excluded.unit,
  selling_price=excluded.selling_price, technical_basis=excluded.technical_basis;
