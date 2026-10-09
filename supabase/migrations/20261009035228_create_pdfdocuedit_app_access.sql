-- Existing remote migration baseline, retrieved and verified 2026-10-09.
-- Already applied to fbzelgtsfoedguyyvxqv; do not replay against that project.
create table public.app_access (
  user_id uuid primary key references auth.users(id) on delete cascade,
  is_active boolean not null default false,
  created_at timestamptz not null default now()
);

comment on table public.app_access is 'Private PDFDocuEdit Pro desktop access allowlist; administrator-controlled only.';
comment on column public.app_access.is_active is 'FALSE by default; only an administrator may enable access.';

alter table public.app_access enable row level security;
revoke all on table public.app_access from public, anon, authenticated;
grant select on table public.app_access to authenticated;

create policy "Users may read own access status"
  on public.app_access
  for select
  to authenticated
  using ((select auth.uid()) = user_id);
