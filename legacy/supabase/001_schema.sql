-- OZ Intelligent Proposal — esquema Supabase/PostgreSQL (MVP)
create extension if not exists pgcrypto;

create type app_role as enum ('ADMIN','MANAGER','ENGINEER','COMMERCIAL','VIEWER');
create type data_origin as enum ('EXTRACTED','UNKNOWN','INFERRED','SUGGESTED','VALIDATED','REQUIRES_REVIEW');
create type proposal_status as enum ('DRAFT','ANALYSING','NEEDS_INFORMATION','TECHNICAL_SCOPE','PRICING','TECHNICAL_REVIEW','READY_FOR_APPROVAL','APPROVED','GENERATED','SENT','CLIENT_REVIEW','ACCEPTED','REJECTED','EXPIRED');

create table profiles (
  id uuid primary key references auth.users on delete cascade,
  full_name text not null, role app_role not null default 'VIEWER', created_at timestamptz default now());

create table clients (id uuid primary key default gen_random_uuid(), name text not null, email_domain text, payment_terms text, created_at timestamptz default now());
create table contacts (id uuid primary key default gen_random_uuid(), client_id uuid references clients on delete cascade, name text, email text);
create table projects (id uuid primary key default gen_random_uuid(), client_id uuid references clients, name text not null, location text, year_built int);

-- Numeração sequencial nunca reutilizada (mesmo em propostas canceladas)
create table counters (name text primary key, value bigint not null);
insert into counters values ('proposal',402),('ref',515),('consulta',26493);
create or replace function next_counter(p_name text) returns bigint language sql as
$$ update counters set value = value + 1 where name = p_name returning value $$;

create table proposal_requests (
  id uuid primary key default gen_random_uuid(),
  consulta_no text unique, client_id uuid references clients, project_id uuid references projects,
  source text check (source in ('chat','email','upload','manual')) default 'chat',
  raw_text text, external_links text[], received_at timestamptz default now(),
  deadline date, status proposal_status default 'DRAFT', created_by uuid references profiles);

create table proposal_analysis (
  id uuid primary key default gen_random_uuid(), request_id uuid references proposal_requests on delete cascade,
  categories text[], checklist_code text, extracted jsonb not null default '{}',   -- cada campo: {value, origin}
  missing_information text[], restrictions text[], created_at timestamptz default now());

create table checklists (code text primary key, title text not null);
create table checklist_items (id serial primary key, checklist_code text references checklists on delete cascade, label text not null, position int);

create table services (
  service_id text primary key, category text, name text not null, unit text default 'un',
  base_cost numeric(12,2) default 0, selling_price numeric(12,2) not null,
  technical_hours numeric(6,1) default 0, equipment_cost numeric(12,2) default 0,
  laboratory_cost numeric(12,2) default 0, travel_cost numeric(12,2) default 0,
  technical_basis text, active boolean default true, version int default 1);
create table service_checklists (service_id text references services, checklist_code text references checklists,
  is_optional boolean default false, default_qty numeric default 1, exclusive_group text, primary key (service_id, checklist_code));

create table proposals (
  id uuid primary key default gen_random_uuid(), request_id uuid references proposal_requests,
  proposal_no text unique, ref_no int, status proposal_status default 'DRAFT',
  vat_rate numeric(4,2) default 23, validity_days int default 30, execution_period text,
  created_by uuid references profiles, created_at timestamptz default now(), approved_by uuid references profiles, approved_at timestamptz);
create table proposal_items (
  id uuid primary key default gen_random_uuid(), proposal_id uuid references proposals on delete cascade,
  service_id text references services, name text not null, unit text, is_optional boolean default false, enabled boolean default true,
  exclusive_group text, suggested_quantity numeric, validated_quantity numeric, unit_price numeric(12,2),
  origin data_origin default 'SUGGESTED', technical_basis text, position int);   -- suggested vs validated alimenta Pricing Intelligence
create table mqt_items (id uuid primary key default gen_random_uuid(), request_id uuid references proposal_requests on delete cascade,
  code text, description text, unit text, quantity numeric, service_id text references services, origin data_origin default 'REQUIRES_REVIEW');
create table proposal_versions (id uuid primary key default gen_random_uuid(), proposal_id uuid references proposals on delete cascade, version int, snapshot jsonb, pdf_path text, created_at timestamptz default now());
create table documents (id uuid primary key default gen_random_uuid(), request_id uuid references proposal_requests, file_name text, storage_path text, kind text);
create table knowledge_documents (id uuid primary key default gen_random_uuid(), title text, service_id text references services, storage_path text);
create table audit_logs (id bigserial primary key, user_id uuid, table_name text, row_id text, action text, old_data jsonb, new_data jsonb, at timestamptz default now());

create or replace function audit() returns trigger language plpgsql security definer as $$
begin insert into audit_logs(user_id,table_name,row_id,action,old_data,new_data)
 values (auth.uid(), tg_table_name, coalesce(new.id::text, old.id::text), tg_op, to_jsonb(old), to_jsonb(new)); return coalesce(new,old); end $$;
create trigger audit_items after insert or update or delete on proposal_items for each row execute function audit();
create trigger audit_proposals after insert or update or delete on proposals for each row execute function audit();

create or replace function my_role() returns app_role language sql stable as $$ select role from profiles where id = auth.uid() $$;
do $$ declare t text; begin
  foreach t in array array['clients','contacts','projects','proposal_requests','proposal_analysis','proposals','proposal_items','mqt_items','proposal_versions','documents','services','checklists','checklist_items','service_checklists','knowledge_documents','counters','audit_logs','profiles'] loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy "ler" on %I for select using (auth.uid() is not null)', t);
    if t not in ('audit_logs') then
      execute format('create policy "escrever" on %I for all using (my_role() in (''ADMIN'',''MANAGER'',''ENGINEER'',''COMMERCIAL'')) with check (my_role() in (''ADMIN'',''MANAGER'',''ENGINEER'',''COMMERCIAL''))', t);
    end if;
  end loop; end $$;

-- Dados iniciais: checklists e catálogo dos casos reais
insert into checklists values ('CRACKING','Fissuração'),('CONCRETE_WATER_EXPOSURE','Betão exposto a água'),('LEVANTAMENTO_INTEGRAL','Levantamento integral'),('MONITORING','Monitorização');
insert into services (service_id,category,name,unit,selling_price,technical_basis) values
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
('VIST_ENV','MONITORING','Vistoria inicial das construções da envolvente + relatório de referência','un',0,'Preço a definir pelo engenheiro');
