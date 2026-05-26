create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default '',
  role text not null default 'route-setter' check (role in ('route-setter', 'admin', 'viewer')),
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.board_templates (
  id text primary key,
  template_key text not null unique,
  label text not null,
  columns integer not null check (columns > 0),
  rows integer not null check (rows > 0),
  hole_spacing_x_mm integer not null check (hole_spacing_x_mm > 0),
  hole_spacing_y_mm integer not null check (hole_spacing_y_mm > 0),
  board_width_mm integer not null check (board_width_mm > 0),
  board_height_mm integer not null check (board_height_mm > 0),
  margins jsonb not null default '{}'::jsonb,
  angle_degrees integer not null default 0,
  material text,
  skin_class text,
  description text,
  is_system boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.board_assets (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.profiles(id) on delete set null,
  route_name text not null,
  setter_commentary text not null default '',
  source_type text not null default 'manual' check (source_type in ('manual', 'ai-generated', 'imported')),
  visibility text not null default 'private' check (visibility in ('private', 'unlisted', 'public')),
  difficulty text not null default 'V3',
  board_template_id text references public.board_templates(id) on delete set null,
  board_spec jsonb,
  tags text[] not null default '{}',
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
