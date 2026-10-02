-- Motor de Atividades de Campo (fase 1).
-- Regra de negócio: o cliente aprova o orçamento do diagnóstico ANTES da ida ao terreno; as atividades
-- BASE e CONDICIONAL previstas ficam no âmbito aprovado e no valor total da proposta.
-- Todas as regras e serviços abaixo são um ponto de partida (preço 0): o engenheiro valida regras e define
-- os preços em services.selling_price. A IA nunca define preços.
-- Idempotente: não altera serviços existentes nem os seus preços.

-- 1) Serviços novos para atividades intrusivas, consequentes e logística (preço 0) ----------------------
insert into public.services(service_id, category, name, unit, selling_price, technical_basis) values
  ('REM_REVEST','INTRUSIVE','Remoção localizada de revestimento','zona',0,'Remoção pontual do revestimento para observar o suporte. Inclui a reposição prevista. Preço a definir pelo engenheiro.'),
  ('ABERT_LOCAL','INTRUSIVE','Abertura localizada para inspeção interna','ponto',0,'Abertura pontual do elemento para observar o interior. Preço a definir pelo engenheiro.'),
  ('EXPOS_ARM','INTRUSIVE','Exposição localizada de armadura','ponto',0,'Exposição pontual da armadura para verificar estado e recobrimento. Preço a definir pelo engenheiro.'),
  ('INSP_INT','SURVEY','Inspeção interna do elemento aberto','ponto',0,'Observação e registo do interior do elemento após a abertura. Preço a definir pelo engenheiro.'),
  ('FECHO_ABERT','REINSTATEMENT','Fecho de abertura localizada','ponto',0,'Fecho da abertura executada para inspeção. Preço a definir pelo engenheiro.'),
  ('REP_REVEST','REINSTATEMENT','Reposição de revestimento na área intervencionada','zona',0,'Reposição do revestimento nas áreas intervencionadas. Preço a definir pelo engenheiro.'),
  ('ACESSO_ESP','LOGISTICS','Meios de acesso especiais (plataforma/andaime)','un',0,'Acesso a elementos em altura ou fachada. Preço a definir pelo engenheiro.')
on conflict (service_id) do nothing;

-- 2) Novos campos em proposal_items (equivalente a proposal_diagnostic_activities) ----------------------
alter table public.proposal_items
  add column if not exists activity_class text check (activity_class in ('BASE', 'CONDITIONAL')),
  add column if not exists trigger_condition text,
  add column if not exists quantity_rule text,
  add column if not exists parent_item_id uuid references public.proposal_items(id) on delete set null,
  add column if not exists included_in_approved_scope boolean not null default true,
  add column if not exists internal_note text;
comment on column public.proposal_items.internal_note is 'Nota interna (patologia, aderência, regra). Nunca vai para o PDF.';
comment on column public.proposal_items.trigger_condition is 'Condição técnica que dispara a atividade condicional. Aparece na proposta.';

-- 3) Regras determinísticas e dependências ----------------------------------------------------------------
create table if not exists public.diagnostic_activity_rules (
  code text primary key,
  service_id text not null references public.services(service_id) on delete cascade,
  activity_class text not null check (activity_class in ('BASE', 'CONDITIONAL')),
  trigger_type text not null check (trigger_type in ('ALWAYS', 'PATHOLOGY_GROUP', 'PATHOLOGY', 'TERM', 'MIN_STOREYS')),
  trigger_value text,
  trigger_condition text,
  quantity_rule text not null default 'FIXED' check (quantity_rule in ('FIXED', 'MANUAL')),
  quantity_value numeric(12,3) not null default 1 check (quantity_value >= 0),
  priority integer not null default 100,
  technical_notes text,
  active boolean not null default true,
  check (trigger_type = 'ALWAYS' or trigger_value is not null)
);

create table if not exists public.diagnostic_activity_dependencies (
  service_id text not null references public.services(service_id) on delete cascade,
  followup_service_id text not null references public.services(service_id) on delete cascade,
  relation text not null default 'REINSTATEMENT' check (relation in ('REINSTATEMENT', 'FOLLOW_UP', 'PREREQUISITE')),
  quantity_ratio numeric(8,3) not null default 1 check (quantity_ratio >= 0),
  note text,
  primary key (service_id, followup_service_id),
  check (service_id <> followup_service_id)
);

insert into public.diagnostic_activity_rules
  (code, service_id, activity_class, trigger_type, trigger_value, trigger_condition, priority, technical_notes) values
  ('R-BASE-MOB',      'MOB',        'BASE',        'ALWAYS',          null, null, 10, 'Regra inicial: validar pelo engenheiro.'),
  ('R-BASE-VISUAL',   'EST_VISUAL', 'BASE',        'ALWAYS',          null, null, 20, 'Inspeção visual, registo fotográfico, medições e relatório preliminar.'),
  ('R-AL-FISSURAS',   'MAP_FISS',   'BASE',        'PATHOLOGY_GROUP', 'AL', null, 30, 'Levantamento das fissuras em alvenaria.'),
  ('R-AL-REVEST',     'REM_REVEST', 'CONDITIONAL', 'PATHOLOGY_GROUP', 'AL', 'o revestimento impedir a observação da fissuração ou do suporte', 40, 'Regra inicial: validar pelo engenheiro.'),
  ('R-AL-ABERTURA',   'ABERT_LOCAL','CONDITIONAL', 'PATHOLOGY_GROUP', 'AL', 'for necessário observar o interior da alvenaria (elementos ocultos, vazios ou armaduras de junta)', 41, 'Regra inicial: validar pelo engenheiro.'),
  ('R-BA-REVEST',     'REM_REVEST', 'CONDITIONAL', 'PATHOLOGY_GROUP', 'BA', 'o revestimento impedir a observação do betão', 40, 'Regra inicial: validar pelo engenheiro.'),
  ('R-BA-ARMADURA',   'EXPOS_ARM',  'CONDITIONAL', 'PATHOLOGY_GROUP', 'BA', 'for necessário confirmar o estado e o recobrimento das armaduras', 41, 'Regra inicial: validar pelo engenheiro.'),
  ('R-HU-REVEST',     'REM_REVEST', 'CONDITIONAL', 'PATHOLOGY_GROUP', 'HU', 'o revestimento impedir localizar a origem da humidade', 40, 'Regra inicial: validar pelo engenheiro.'),
  ('R-HU-ABERTURA',   'ABERT_LOCAL','CONDITIONAL', 'PATHOLOGY_GROUP', 'HU', 'for necessário localizar tubagem embutida ou a origem da humidade', 41, 'Regra inicial: validar pelo engenheiro.'),
  ('R-IH-REVEST',     'REM_REVEST', 'CONDITIONAL', 'PATHOLOGY_GROUP', 'IH', 'o revestimento impedir aceder à tubagem ou à ligação', 40, 'Regra inicial: validar pelo engenheiro.'),
  ('R-IH-ABERTURA',   'ABERT_LOCAL','CONDITIONAL', 'PATHOLOGY_GROUP', 'IH', 'for necessário localizar tubagem embutida ou a fuga', 41, 'Regra inicial: validar pelo engenheiro.'),
  ('R-ACESSO-PISOS',  'ACESSO_ESP', 'CONDITIONAL', 'MIN_STOREYS',     '4',  'o acesso ao elemento exigir plataforma ou andaime', 60, 'Edifícios com 4 ou mais pisos.'),
  ('R-ACESSO-FACHADA','ACESSO_ESP', 'CONDITIONAL', 'TERM',            'fachada',   'o acesso ao elemento exigir plataforma ou andaime', 61, null),
  ('R-ACESSO-COBERT', 'ACESSO_ESP', 'CONDITIONAL', 'TERM',            'cobertura', 'o acesso ao elemento exigir plataforma ou andaime', 62, null)
on conflict (code) do nothing;

insert into public.diagnostic_activity_dependencies(service_id, followup_service_id, relation, note) values
  ('ABERT_LOCAL', 'INSP_INT',    'FOLLOW_UP',     'A abertura só faz sentido com a inspeção interna.'),
  ('ABERT_LOCAL', 'FECHO_ABERT', 'REINSTATEMENT', 'Toda a abertura tem de ser fechada.'),
  ('FECHO_ABERT', 'REP_REVEST',  'REINSTATEMENT', 'O fecho exige reposição do revestimento.'),
  ('REM_REVEST',  'REP_REVEST',  'REINSTATEMENT', 'A remoção exige reposição do revestimento.'),
  ('EXPOS_ARM',   'REP_REVEST',  'REINSTATEMENT', 'A exposição da armadura exige reposição.')
on conflict do nothing;

-- 4) Hipóteses de solução (INFORMAÇÃO INTERNA; nunca constam da proposta) ----------------------------------
create table if not exists public.proposal_solution_hypotheses (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  request_id uuid not null references public.proposal_requests(id) on delete cascade,
  pathology_code text not null,
  solution_code text not null,
  solution_name text not null,
  evidence text,
  status text not null default 'PREDICTED' check (status in ('PREDICTED', 'CONFIRMED', 'DISPROVED', 'NOT_EVALUATED')),
  field_note text,
  created_at timestamptz not null default now(),
  unique (request_id, pathology_code, solution_code)
);
create index if not exists proposal_solution_hypotheses_request_idx on public.proposal_solution_hypotheses(request_id);
comment on table public.proposal_solution_hypotheses is
  'Soluções prováveis sugeridas pela base técnica durante a proposta. Só informação interna: comparam-se com o diagnóstico de campo.';

-- 5) Segurança -------------------------------------------------------------------------------------------
alter table public.proposal_solution_hypotheses enable row level security;
drop policy if exists "owners manage solution hypotheses" on public.proposal_solution_hypotheses;
create policy "owners manage solution hypotheses" on public.proposal_solution_hypotheses
  for all to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));
grant select, insert, update, delete on public.proposal_solution_hypotheses to authenticated;

do $$ declare t text; begin
  foreach t in array array['diagnostic_activity_rules', 'diagnostic_activity_dependencies'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists "kb_ler" on public.%I', t);
    execute format('create policy "kb_ler" on public.%I for select using (auth.uid() is not null)', t);
    execute format('drop policy if exists "kb_escrever" on public.%I', t);
    execute format('create policy "kb_escrever" on public.%I for all using (my_role() in (''ADMIN'',''MANAGER'',''ENGINEER'')) with check (my_role() in (''ADMIN'',''MANAGER'',''ENGINEER''))', t);
  end loop; end $$;
grant select, insert, update, delete on public.diagnostic_activity_rules, public.diagnostic_activity_dependencies to authenticated;
