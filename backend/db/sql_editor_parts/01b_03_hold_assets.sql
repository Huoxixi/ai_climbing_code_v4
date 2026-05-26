create table if not exists public.hold_assets (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.profiles(id) on delete set null,
  hold_type text not null check (hold_type in ('Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot')),
  variant text not null,
  image_path text,
  public_image_url text,
  svg_path text,
  metadata jsonb not null default '{}'::jsonb,
  is_system boolean not null default false,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
