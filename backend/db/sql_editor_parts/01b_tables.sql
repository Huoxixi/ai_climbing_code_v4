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

create table if not exists public.ai_generation_tasks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.profiles(id) on delete set null,
  mode text not null check (mode in ('compose_route', 'review_route', 'legacy_generate')),
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed', 'cancelled')),
  request_payload jsonb not null default '{}'::jsonb,
  result_payload jsonb,
  error_message text,
  source_board_asset_id uuid references public.board_assets(id) on delete set null,
  result_board_asset_id uuid references public.board_assets(id) on delete set null,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.route_review_findings (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.ai_generation_tasks(id) on delete cascade,
  board_asset_id uuid references public.board_assets(id) on delete cascade,
  finding_type text not null check (finding_type in ('violation', 'suggestion')),
  code text,
  title text,
  detail text not null,
  hold_ids text[] not null default '{}',
  risk_level text check (risk_level in ('low', 'medium', 'high')),
  created_at timestamptz not null default now()
);

create table if not exists public.route_feedback (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.profiles(id) on delete set null,
  board_asset_id uuid references public.board_assets(id) on delete set null,
  task_id uuid references public.ai_generation_tasks(id) on delete set null,
  rating integer check (rating between 1 and 5),
  feedback_type text not null check (feedback_type in ('good_pattern', 'bad_move', 'bug', 'preference')),
  content text not null,
  hold_ids text[] not null default '{}',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

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
