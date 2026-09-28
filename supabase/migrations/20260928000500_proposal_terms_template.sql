-- New proposal drafts follow the 60-day validity used by the supplied OZ proposal template.
-- Engineers can change the period and execution schedule on each proposal before approval.
alter table public.proposals
  alter column validity_days set default 60;
