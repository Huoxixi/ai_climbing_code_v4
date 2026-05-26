create table if not exists public.route_learning_patterns (
  id text primary key,
  name text not null,
  description text not null,
  signals text[] not null default '{}',
  difficulty_scope text[] not null default '{}',
  source_feedback_id uuid references public.route_feedback(id) on delete set null,
  enabled boolean not null default true,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.modification_logs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.profiles(id) on delete set null,
  module text not null,
  board_asset_id uuid references public.board_assets(id) on delete set null,
  changes text[] not null default '{}',
  reason text[] not null default '{}',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
