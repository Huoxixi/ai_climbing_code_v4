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

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'profiles_select_own') then
    create policy "profiles_select_own" on public.profiles for select to authenticated using (id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'profiles_insert_own') then
    create policy "profiles_insert_own" on public.profiles for insert to authenticated with check (id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'profiles_update_own') then
    create policy "profiles_update_own" on public.profiles for update to authenticated using (id = auth.uid()) with check (id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'board_templates' and policyname = 'board_templates_read_all') then
    create policy "board_templates_read_all" on public.board_templates for select to anon, authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'hold_assets' and policyname = 'hold_assets_read_available') then
    create policy "hold_assets_read_available" on public.hold_assets for select to authenticated using (archived_at is null and (is_system or owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'hold_assets' and policyname = 'hold_assets_insert_own') then
    create policy "hold_assets_insert_own" on public.hold_assets for insert to authenticated with check (owner_id = auth.uid() and is_system = false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'hold_assets' and policyname = 'hold_assets_update_own') then
    create policy "hold_assets_update_own" on public.hold_assets for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid() and is_system = false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'hold_assets' and policyname = 'hold_assets_delete_own') then
    create policy "hold_assets_delete_own" on public.hold_assets for delete to authenticated using (owner_id = auth.uid() and is_system = false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'board_assets' and policyname = 'board_assets_read_allowed') then
    create policy "board_assets_read_allowed" on public.board_assets for select to authenticated using (archived_at is null and (owner_id = auth.uid() or visibility = 'public'));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'board_assets' and policyname = 'board_assets_insert_own') then
    create policy "board_assets_insert_own" on public.board_assets for insert to authenticated with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'board_assets' and policyname = 'board_assets_update_own') then
    create policy "board_assets_update_own" on public.board_assets for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'board_assets' and policyname = 'board_assets_delete_own') then
    create policy "board_assets_delete_own" on public.board_assets for delete to authenticated using (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_holds' and policyname = 'route_holds_read_allowed') then
    create policy "route_holds_read_allowed" on public.route_holds for select to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.archived_at is null and (b.owner_id = auth.uid() or b.visibility = 'public')));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_holds' and policyname = 'route_holds_insert_own') then
    create policy "route_holds_insert_own" on public.route_holds for insert to authenticated with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_holds' and policyname = 'route_holds_update_own') then
    create policy "route_holds_update_own" on public.route_holds for update to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid())) with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_holds' and policyname = 'route_holds_delete_own') then
    create policy "route_holds_delete_own" on public.route_holds for delete to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_beta_steps' and policyname = 'route_beta_steps_read_allowed') then
    create policy "route_beta_steps_read_allowed" on public.route_beta_steps for select to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.archived_at is null and (b.owner_id = auth.uid() or b.visibility = 'public')));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_beta_steps' and policyname = 'route_beta_steps_insert_own') then
    create policy "route_beta_steps_insert_own" on public.route_beta_steps for insert to authenticated with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_beta_steps' and policyname = 'route_beta_steps_update_own') then
    create policy "route_beta_steps_update_own" on public.route_beta_steps for update to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid())) with check (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_beta_steps' and policyname = 'route_beta_steps_delete_own') then
    create policy "route_beta_steps_delete_own" on public.route_beta_steps for delete to authenticated using (exists (select 1 from public.board_assets b where b.id = board_asset_id and b.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'ai_generation_tasks' and policyname = 'ai_generation_tasks_select_own') then
    create policy "ai_generation_tasks_select_own" on public.ai_generation_tasks for select to authenticated using (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'ai_generation_tasks' and policyname = 'ai_generation_tasks_insert_own') then
    create policy "ai_generation_tasks_insert_own" on public.ai_generation_tasks for insert to authenticated with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'ai_generation_tasks' and policyname = 'ai_generation_tasks_update_own') then
    create policy "ai_generation_tasks_update_own" on public.ai_generation_tasks for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_review_findings' and policyname = 'route_review_findings_select_own') then
    create policy "route_review_findings_select_own" on public.route_review_findings for select to authenticated using (exists (select 1 from public.ai_generation_tasks t where t.id = task_id and t.owner_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_feedback' and policyname = 'route_feedback_select_own') then
    create policy "route_feedback_select_own" on public.route_feedback for select to authenticated using (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_feedback' and policyname = 'route_feedback_insert_own') then
    create policy "route_feedback_insert_own" on public.route_feedback for insert to authenticated with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_feedback' and policyname = 'route_feedback_update_own') then
    create policy "route_feedback_update_own" on public.route_feedback for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'route_learning_patterns' and policyname = 'route_learning_patterns_read_enabled') then
    create policy "route_learning_patterns_read_enabled" on public.route_learning_patterns for select to anon, authenticated using (enabled = true);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'modification_logs' and policyname = 'modification_logs_select_own') then
    create policy "modification_logs_select_own" on public.modification_logs for select to authenticated using (owner_id = auth.uid());
  end if;
end $$;
