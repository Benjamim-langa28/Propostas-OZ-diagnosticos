-- Permite remover rascunhos do próprio utilizador pelo dashboard.
drop policy if exists "Users delete own OZ drafts" on public.oz_drafts;
create policy "Users delete own OZ drafts" on public.oz_drafts
  for delete to authenticated using (owner = (select auth.uid()));
grant delete on public.oz_drafts to authenticated;
