-- Armazenamento temporário do MVP: preserva o documento completo da proposta
-- enquanto o frontend migra para proposal_requests/proposals/proposal_items.
create table if not exists public.oz_drafts (
  owner uuid not null references auth.users(id) on delete cascade,
  id bigint not null,
  data jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (owner, id)
);

create index if not exists oz_drafts_owner_updated_idx
  on public.oz_drafts (owner, updated_at desc);

alter table public.oz_drafts enable row level security;

drop policy if exists "Users read own OZ drafts" on public.oz_drafts;
create policy "Users read own OZ drafts" on public.oz_drafts
  for select to authenticated using (owner = (select auth.uid()));

drop policy if exists "Users insert own OZ drafts" on public.oz_drafts;
create policy "Users insert own OZ drafts" on public.oz_drafts
  for insert to authenticated with check (owner = (select auth.uid()));

drop policy if exists "Users update own OZ drafts" on public.oz_drafts;
create policy "Users update own OZ drafts" on public.oz_drafts
  for update to authenticated using (owner = (select auth.uid()))
  with check (owner = (select auth.uid()));

grant select, insert, update on public.oz_drafts to authenticated;
