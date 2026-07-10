create table if not exists public.standard_route_favorites (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete cascade,
  source_id text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, source_id)
);

create table if not exists public.standard_route_ascent_logs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete cascade,
  source_id text not null,
  result text not null check (result in ('flash', 'send', 'attempt', 'fail')),
  attempts integer not null default 1 check (attempts > 0),
  perceived_grade text,
  notes text not null default '',
  created_at timestamptz not null default now()
);

alter table public.standard_route_favorites enable row level security;
alter table public.standard_route_ascent_logs enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'standard_route_favorites' and policyname = 'standard_route_favorites_select_own') then
    create policy "standard_route_favorites_select_own" on public.standard_route_favorites for select to authenticated using (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'standard_route_favorites' and policyname = 'standard_route_favorites_insert_own') then
    create policy "standard_route_favorites_insert_own" on public.standard_route_favorites for insert to authenticated with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'standard_route_favorites' and policyname = 'standard_route_favorites_update_own') then
    create policy "standard_route_favorites_update_own" on public.standard_route_favorites for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'standard_route_ascent_logs' and policyname = 'standard_route_ascent_logs_select_own') then
    create policy "standard_route_ascent_logs_select_own" on public.standard_route_ascent_logs for select to authenticated using (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'standard_route_ascent_logs' and policyname = 'standard_route_ascent_logs_insert_own') then
    create policy "standard_route_ascent_logs_insert_own" on public.standard_route_ascent_logs for insert to authenticated with check (owner_id = auth.uid());
  end if;
end $$;
