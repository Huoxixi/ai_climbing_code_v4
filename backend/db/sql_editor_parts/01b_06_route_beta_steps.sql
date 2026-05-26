create table if not exists public.route_beta_steps (
  id uuid primary key default gen_random_uuid(),
  board_asset_id uuid not null references public.board_assets(id) on delete cascade,
  step_index integer not null check (step_index >= 0),
  limb text not null check (limb in ('LH', 'RH', 'LF', 'RF')),
  hold_coord_id text not null,
  intent text not null default 'Move',
  is_top boolean not null default false,
  lh text,
  rh text,
  lf text,
  rf text,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (board_asset_id, step_index)
);
