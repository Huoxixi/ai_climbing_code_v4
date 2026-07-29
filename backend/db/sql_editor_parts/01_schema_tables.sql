create extension if not exists pgcrypto with schema extensions;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

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

create unique index if not exists hold_assets_owner_variant_idx on public.hold_assets(owner_id, hold_type, variant) where owner_id is not null and archived_at is null;
create unique index if not exists hold_assets_system_variant_idx on public.hold_assets(hold_type, variant) where owner_id is null and archived_at is null;

create table if not exists public.board_assets (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.profiles(id) on delete set null,
  route_name text not null,
  setter_commentary text not null default '',
  source_type text not null default 'manual' check (source_type in ('manual', 'ai-generated', 'imported')),
  visibility text not null default 'private' check (visibility in ('private', 'unlisted', 'public')),
  difficulty text not null default '未定级',
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

create index if not exists board_assets_owner_updated_idx on public.board_assets(owner_id, updated_at desc) where archived_at is null;
create index if not exists board_assets_visibility_idx on public.board_assets(visibility) where archived_at is null;
create index if not exists route_holds_board_idx on public.route_holds(board_asset_id, sort_order);
create index if not exists route_beta_steps_board_idx on public.route_beta_steps(board_asset_id, step_index);
create index if not exists hold_assets_lookup_idx on public.hold_assets(hold_type, variant) where archived_at is null;
create index if not exists ai_generation_tasks_owner_created_idx on public.ai_generation_tasks(owner_id, created_at desc);

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'profiles_set_updated_at') then
    execute 'create trigger profiles_set_updated_at before update on public.profiles for each row execute function public.set_updated_at()';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'board_templates_set_updated_at') then
    execute 'create trigger board_templates_set_updated_at before update on public.board_templates for each row execute function public.set_updated_at()';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'hold_assets_set_updated_at') then
    execute 'create trigger hold_assets_set_updated_at before update on public.hold_assets for each row execute function public.set_updated_at()';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'board_assets_set_updated_at') then
    execute 'create trigger board_assets_set_updated_at before update on public.board_assets for each row execute function public.set_updated_at()';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'ai_generation_tasks_set_updated_at') then
    execute 'create trigger ai_generation_tasks_set_updated_at before update on public.ai_generation_tasks for each row execute function public.set_updated_at()';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'route_learning_patterns_set_updated_at') then
    execute 'create trigger route_learning_patterns_set_updated_at before update on public.route_learning_patterns for each row execute function public.set_updated_at()';
  end if;
end $$;
