-- Catálogo-rascunho de serviços e ligações entre a base técnica e o orçamento.
-- Todos os serviços novos entram com preço 0: o engenheiro define preços em services.selling_price.
-- Idempotente: não altera serviços existentes nem os seus preços.

create table if not exists public.kb_test_services (
  test_code text not null references public.kb_tests(code) on delete cascade,
  service_id text not null references public.services(service_id) on delete cascade,
  primary key (test_code, service_id));
create table if not exists public.kb_solution_services (
  solution_code text not null references public.kb_solutions(code) on delete cascade,
  service_id text not null references public.services(service_id) on delete cascade,
  primary key (solution_code, service_id));

insert into public.services(service_id, category, name, unit, selling_price, technical_basis) values
  ('LEV_DIM','SURVEY','Levantamento dimensional / geométrico','zona',0,'Levantamento de geometria dos elementos afetados. Preço a definir pelo engenheiro.'),
  ('MAP_FISS','SURVEY','Mapeamento e medição da abertura de fissuras','zona',0,'Cartografia de fissuras com largura, orientação e extensão. Preço a definir pelo engenheiro.'),
  ('NIVEL','SURVEY','Nivelamento e estação total','zona',0,'Deteção de assentamentos e deformações. Preço a definir pelo engenheiro.'),
  ('LASER','SURVEY','Nuvem de pontos / laser scanner','un',0,'Levantamento tridimensional. Preço a definir pelo engenheiro.'),
  ('DRONE','SURVEY','Inspeção por drone','un',0,'Zonas de difícil acesso (fachadas, coberturas). Preço a definir pelo engenheiro.'),
  ('ESCLER','NDT','Esclerometria (NP EN 12504-2)','zona',0,'Estimativa da dureza superficial do betão. Preço a definir pelo engenheiro.'),
  ('ULTRAS','NDT','Ultrassons em betão (NP EN 12504-4)','zona',0,'Homogeneidade e fissuração interna. Preço a definir pelo engenheiro.'),
  ('GEORADAR','NDT','Georradar','zona',0,'Deteção de armaduras, vazios e descontinuidades. Preço a definir pelo engenheiro.'),
  ('POT_CORR','NDT','Potencial de corrosão - half-cell (ASTM C876)','zona',0,'Probabilidade de corrosão ativa das armaduras. Preço a definir pelo engenheiro.'),
  ('RESIST_ELE','NDT','Resistividade elétrica do betão','zona',0,'Agressividade do meio e risco de corrosão. Preço a definir pelo engenheiro.'),
  ('PULLOFF','NDT','Arrancamento / pull-off','ponto',0,'Aderência de reparações e revestimentos. Preço a definir pelo engenheiro.'),
  ('TRAC_ARM','NDT','Ensaios de tração e análise de armaduras','un',0,'Caracterização mecânica do aço. Preço a definir pelo engenheiro.'),
  ('PETROG','NDT','Petrografia / diagnóstico de RAS','un',0,'Reações expansivas do betão. Preço a definir pelo engenheiro.'),
  ('ABSORC','NDT','Absorção de água do betão','ponto',0,'Porosidade e permeabilidade. Preço a definir pelo engenheiro.'),
  ('PROVA_CARGA','NDT','Prova de carga','un',0,'Verificação do comportamento em serviço. Preço a definir pelo engenheiro.'),
  ('MED_HUM','NDT','Medição de humidade','zona',0,'Humidade nos materiais e paredes. Preço a definir pelo engenheiro.'),
  ('TERMOG','NDT','Termografia','zona',0,'Deteção de humidade e anomalias térmicas. Preço a definir pelo engenheiro.'),
  ('SONIC_ALV','NDT','Ensaios sónicos / ultrassons em alvenaria','zona',0,'Homogeneidade e consolidação de alvenarias. Preço a definir pelo engenheiro.'),
  ('ENDOSC','NDT','Endoscopia','ponto',0,'Inspeção de cavidades e interior de elementos. Preço a definir pelo engenheiro.'),
  ('SOND_INSP','NDT','Sondagens de inspeção e janelas de observação','ponto',0,'Observação direta de elementos ocultos. Preço a definir pelo engenheiro.'),
  ('US_MAD','NDT','Ultrassons e humidade em madeira','zona',0,'Estado de conservação de elementos de madeira. Preço a definir pelo engenheiro.'),
  ('ESP_US','NDT','Medição de espessura por ultrassons (metal)','ponto',0,'Perda de secção por corrosão. Preço a definir pelo engenheiro.'),
  ('LP_PM','NDT','Líquidos penetrantes / partículas magnéticas / soldaduras','ponto',0,'Deteção de fissuras em soldaduras e metal. Preço a definir pelo engenheiro.'),
  ('GEOT_PROSP','GEOTECHNICAL','Prospeção geotécnica (SPT, CPT, sondagens)','un',0,'Caracterização do terreno de fundação. Preço a definir pelo engenheiro.'),
  ('POCOS_FUND','GEOTECHNICAL','Poços de reconhecimento de fundações','un',0,'Observação direta das fundações. Preço a definir pelo engenheiro.'),
  ('PIEZ','MONITORING','Piezómetros','un',0,'Nível freático. Preço a definir pelo engenheiro.'),
  ('EXTENS','MONITORING','Extensómetros / deformímetros','un',0,'Deformação de elementos. Preço a definir pelo engenheiro.'),
  ('CLINOM','MONITORING','Clinómetros / inclinómetros','un',0,'Rotações e inclinações. Preço a definir pelo engenheiro.'),
  ('SENS_HT','MONITORING','Sensores de humidade e temperatura','un',0,'Registo contínuo de humidade e temperatura. Preço a definir pelo engenheiro.'),
  ('VIBR','MONITORING','Monitorização de vibrações','un',0,'Vibrações induzidas por obras ou tráfego. Preço a definir pelo engenheiro.'),
  ('PROJ_REAB','STUDY','Especificação técnica da solução de reparação/reforço','un',0,'Definição da solução, materiais e mapa de quantidades. A execução da obra não está incluída. Preço a definir pelo engenheiro.'),
  ('PROJ_ESCOR','STUDY','Projeto de escoramento provisório','un',0,'Redução de cargas e escoramento. Preço a definir pelo engenheiro.'),
  ('EST_COMPL','STUDY','Investigação complementar dirigida','un',0,'Estudo adicional quando o diagnóstico não é conclusivo. Preço a definir pelo engenheiro.'),
  ('SEG_IMED','STUDY','Parecer e medidas de segurança imediatas','un',0,'Isolamento da área e medidas urgentes. Preço a definir pelo engenheiro.')
on conflict (service_id) do nothing;

insert into public.kb_test_services(test_code, service_id) values
  ('ENS-01','EST_VISUAL'),
  ('ENS-02','LEV_DIM'),
  ('ENS-03','MAP_FISS'),
  ('ENS-04','MAP_FISS'),
  ('ENS-05','FISS_M1'),
  ('ENS-06','NIVEL'),
  ('ENS-07','LASER'),
  ('ENS-08','DRONE'),
  ('ENS-10','ESCLER'),
  ('ENS-11','ULTRAS'),
  ('ENS-12','PACO'),
  ('ENS-13','GEORADAR'),
  ('ENS-14','POT_CORR'),
  ('ENS-15','RESIST_ELE'),
  ('ENS-16','CARB'),
  ('ENS-17','CLOR'),
  ('ENS-18','CAROTE'),
  ('ENS-19','PULLOFF'),
  ('ENS-20','TRAC_ARM'),
  ('ENS-21','PETROG'),
  ('ENS-22','ABSORC'),
  ('ENS-23','PROVA_CARGA'),
  ('ENS-30','MED_HUM'),
  ('ENS-31','TERMOG'),
  ('ENS-40','MACACO'),
  ('ENS-41','SONIC_ALV'),
  ('ENS-42','ENDOSC'),
  ('ENS-43','SOND_INSP'),
  ('ENS-50','RESIST'),
  ('ENS-51','US_MAD'),
  ('ENS-60','ESP_US'),
  ('ENS-61','LP_PM'),
  ('ENS-70','GEOT_PROSP'),
  ('ENS-71','POCOS_FUND'),
  ('ENS-72','PIEZ'),
  ('ENS-80','EXTENS'),
  ('ENS-81','CLINOM'),
  ('ENS-82','SENS_HT'),
  ('ENS-83','VIBR')
on conflict do nothing;

insert into public.kb_solution_services(solution_code, service_id) values
  ('SOL-01','PROJ_REAB'),
  ('SOL-02','PROJ_REAB'),
  ('SOL-03','PROJ_REAB'),
  ('SOL-04','PROJ_REAB'),
  ('SOL-05','PROJ_REAB'),
  ('SOL-06','PROJ_REAB'),
  ('SOL-07','PROJ_REAB'),
  ('SOL-08','PROJ_REAB'),
  ('SOL-09','PROJ_REAB'),
  ('SOL-10','PROJ_REAB'),
  ('SOL-11','PROJ_REAB'),
  ('SOL-12','PROJ_REAB'),
  ('SOL-13','PROJ_REAB'),
  ('SOL-14','PROJ_REAB'),
  ('SOL-15','PROJ_REAB'),
  ('SOL-16','PROJ_REAB'),
  ('SOL-17','PROJ_REAB'),
  ('SOL-18','PROJ_REAB'),
  ('SOL-19','PROJ_REAB'),
  ('SOL-20','PROJ_REAB'),
  ('SOL-21','PROJ_REAB'),
  ('SOL-22','PROJ_REAB'),
  ('SOL-23','PROJ_REAB'),
  ('SOL-24','PROJ_REAB'),
  ('SOL-25','PROJ_ESCOR'),
  ('SOL-26','FISS_M2'),
  ('SOL-27','PROJ_REAB'),
  ('SOL-28','EST_COMPL'),
  ('SOL-29','SEG_IMED')
on conflict do nothing;

do $$ declare t text; begin
  foreach t in array array['kb_test_services','kb_solution_services'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists "kb_ler" on public.%I', t);
    execute format('create policy "kb_ler" on public.%I for select using (auth.uid() is not null)', t);
    execute format('drop policy if exists "kb_escrever" on public.%I', t);
    execute format('create policy "kb_escrever" on public.%I for all using (my_role() in (''ADMIN'',''MANAGER'',''ENGINEER'')) with check (my_role() in (''ADMIN'',''MANAGER'',''ENGINEER''))', t);
  end loop; end $$;
grant select, insert, update, delete on public.kb_test_services, public.kb_solution_services to authenticated;
