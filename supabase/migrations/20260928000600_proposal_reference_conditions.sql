-- Preserve the reference proposal's execution schedule on newly created drafts.
alter table public.proposals
  alter column validity_days set default 60,
  alter column execution_period set default 'Início dos trabalhos: a combinar. Duração da inspeção visual e elaboração do relatório: 3 semanas. Duração dos ensaios e elaboração do relatório respetivo: 5 semanas.';
