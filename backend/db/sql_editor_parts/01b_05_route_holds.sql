create table if not exists public.route_holds (
  id uuid primary key default gen_random_uuid(),
  board_asset_id uuid not null references public.board_assets(id) on delete cascade,
  coord_id text not null,
  x_label text not null,
  y_index integer not null check (y_index > 0),
  hold_type text not null check (hold_type in ('Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot')),
  hold_asset_id uuid references public.hold_assets(id) on delete set null,
  variant text not null default 'default',
  rotation integer not null default 0 check (rotation >= 0 and rotation < 360),
  scale numeric not null default 1 check (scale > 0),
  is_start boolean not null default false,
  sort_order integer not null default 0,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (board_asset_id, coord_id)
);
