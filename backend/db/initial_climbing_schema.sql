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

create index if not exists board_assets_owner_updated_idx on public.board_assets(owner_id, updated_at desc) where archived_at is null;
create index if not exists board_assets_visibility_idx on public.board_assets(visibility) where archived_at is null;
create index if not exists route_holds_board_idx on public.route_holds(board_asset_id, sort_order);
create index if not exists route_beta_steps_board_idx on public.route_beta_steps(board_asset_id, step_index);
create index if not exists hold_assets_lookup_idx on public.hold_assets(hold_type, variant) where archived_at is null;
create index if not exists ai_generation_tasks_owner_created_idx on public.ai_generation_tasks(owner_id, created_at desc);

create trigger profiles_set_updated_at before update on public.profiles for each row execute function public.set_updated_at();
create trigger board_templates_set_updated_at before update on public.board_templates for each row execute function public.set_updated_at();
create trigger hold_assets_set_updated_at before update on public.hold_assets for each row execute function public.set_updated_at();
create trigger board_assets_set_updated_at before update on public.board_assets for each row execute function public.set_updated_at();
create trigger ai_generation_tasks_set_updated_at before update on public.ai_generation_tasks for each row execute function public.set_updated_at();
create trigger route_learning_patterns_set_updated_at before update on public.route_learning_patterns for each row execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name, role, avatar_url)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'name', new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), ''),
    'route-setter',
    new.raw_user_meta_data->>'avatar_url'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke execute on function public.handle_new_user() from anon, authenticated;

drop trigger if exists on_auth_user_created_create_profile on auth.users;
create trigger on_auth_user_created_create_profile after insert on auth.users for each row execute function public.handle_new_user();

insert into public.board_templates (id, template_key, label, columns, rows, hole_spacing_x_mm, hole_spacing_y_mm, board_width_mm, board_height_mm, margins, angle_degrees, material, skin_class, description, is_system)
values
  ('classic-11x18', 'spray-small', 'MoonBoard 风格标准板', 11, 18, 200, 200, 2440, 3660, '{"left":220,"right":220,"bottom":130,"top":130}', 40, '深色木纹复合板', 'skin-wood-classic', '以 200mm 孔距和 11 x 18 坐标作为 AI 生成默认规格，兼容现有路线算法。', true),
  ('studio-14x20', 'spray-medium', 'Studio 扩展喷点板', 14, 20, 200, 200, 3040, 4060, '{"left":220,"right":220,"bottom":130,"top":130}', 10, '桦木纹理 + 密集孔位', 'skin-birch-studio', '系统扩展规格，适合中等规模手动布点和自由组合岩点。', true),
  ('commercial-16x24', 'spray-large', 'Commercial 大型喷点板', 16, 24, 200, 200, 3440, 4860, '{"left":220,"right":220,"bottom":130,"top":130}', 15, '灰黑防滑板面', 'skin-commercial-dark', '系统扩展规格，提供更多横向移动空间和更高的路线容量。', true),
  ('competition-18x22', 'competition-wide', 'Competition 宽体训练板', 18, 22, 200, 200, 3840, 4460, '{"left":220,"right":220,"bottom":130,"top":130}', 20, '蓝灰竞赛板面', 'skin-competition-blue', '系统扩展规格，适合大跨度横移、协调动作和复杂组合模拟。', true)
on conflict (id) do update set
  template_key = excluded.template_key,
  label = excluded.label,
  columns = excluded.columns,
  rows = excluded.rows,
  hole_spacing_x_mm = excluded.hole_spacing_x_mm,
  hole_spacing_y_mm = excluded.hole_spacing_y_mm,
  board_width_mm = excluded.board_width_mm,
  board_height_mm = excluded.board_height_mm,
  margins = excluded.margins,
  angle_degrees = excluded.angle_degrees,
  material = excluded.material,
  skin_class = excluded.skin_class,
  description = excluded.description,
  is_system = excluded.is_system;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('hold-images', 'hold-images', true, 5242880, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

alter table public.profiles enable row level security;
alter table public.board_templates enable row level security;
alter table public.hold_assets enable row level security;
alter table public.board_assets enable row level security;
alter table public.route_holds enable row level security;
alter table public.route_beta_steps enable row level security;
alter table public.ai_generation_tasks enable row level security;
alter table public.route_review_findings enable row level security;
alter table public.route_feedback enable row level security;
alter table public.route_learning_patterns enable row level security;
alter table public.modification_logs enable row level security;

create policy "profiles_select_own" on public.profiles for select to authenticated using (id = auth.uid());
create policy "profiles_insert_own" on public.profiles for insert to authenticated with check (id = auth.uid());
create policy "profiles_update_own" on public.profiles for update to authenticated using (id = auth.uid()) with check (id = auth.uid());
create policy "board_templates_read_all" on public.board_templates for select to anon, authenticated using (true);
create policy "hold_assets_read_available" on public.hold_assets for select to authenticated using (archived_at is null and (is_system or owner_id = auth.uid()));
create policy "hold_assets_insert_own" on public.hold_assets for insert to authenticated with check (owner_id = auth.uid() and is_system = false);
create policy "hold_assets_update_own" on public.hold_assets for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid() and is_system = false);
create policy "hold_assets_delete_own" on public.hold_assets for delete to authenticated using (owner_id = auth.uid() and is_system = false);
create policy "board_assets_read_allowed" on public.board_assets for select to authenticated using (archived_at is null and (owner_id = auth.uid() or visibility = 'public'));
create policy "board_assets_insert_own" on public.board_assets for insert to authenticated with check (owner_id = auth.uid());
create policy "board_assets_update_own" on public.board_assets for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "board_assets_delete_own" on public.board_assets for delete to authenticated using (owner_id = auth.uid());
create policy "route_holds_read_allowed" on public.route_holds for select to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.archived_at is null and (b.owner_id = auth.uid() or b.visibility = 'public')));
create policy "route_holds_insert_own" on public.route_holds for insert to authenticated with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
create policy "route_holds_update_own" on public.route_holds for update to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid())) with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
create policy "route_holds_delete_own" on public.route_holds for delete to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
create policy "route_beta_steps_read_allowed" on public.route_beta_steps for select to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.archived_at is null and (b.owner_id = auth.uid() or b.visibility = 'public')));
create policy "route_beta_steps_insert_own" on public.route_beta_steps for insert to authenticated with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
create policy "route_beta_steps_update_own" on public.route_beta_steps for update to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid())) with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
create policy "route_beta_steps_delete_own" on public.route_beta_steps for delete to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
create policy "ai_generation_tasks_select_own" on public.ai_generation_tasks for select to authenticated using (owner_id = auth.uid());
create policy "ai_generation_tasks_insert_own" on public.ai_generation_tasks for insert to authenticated with check (owner_id = auth.uid());
create policy "ai_generation_tasks_update_own" on public.ai_generation_tasks for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "route_review_findings_select_own" on public.route_review_findings for select to authenticated using (exists (select 1 from public.ai_generation_tasks t where t.id = task_id and t.owner_id = auth.uid()));
create policy "route_feedback_select_own" on public.route_feedback for select to authenticated using (owner_id = auth.uid());
create policy "route_feedback_insert_own" on public.route_feedback for insert to authenticated with check (owner_id = auth.uid());
create policy "route_feedback_update_own" on public.route_feedback for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "route_learning_patterns_read_enabled" on public.route_learning_patterns for select to anon, authenticated using (enabled = true);
create policy "modification_logs_select_own" on public.modification_logs for select to authenticated using (owner_id = auth.uid());
create policy "hold_images_public_read" on storage.objects for select to anon, authenticated using (bucket_id = 'hold-images');
create policy "hold_images_user_insert" on storage.objects for insert to authenticated with check (bucket_id = 'hold-images' and (storage.foldername(name))[1] = 'users' and (storage.foldername(name))[2] = auth.uid()::text);
create policy "hold_images_user_update" on storage.objects for update to authenticated using (bucket_id = 'hold-images' and (storage.foldername(name))[1] = 'users' and (storage.foldername(name))[2] = auth.uid()::text);
create policy "hold_images_user_delete" on storage.objects for delete to authenticated using (bucket_id = 'hold-images' and (storage.foldername(name))[1] = 'users' and (storage.foldername(name))[2] = auth.uid()::text);
