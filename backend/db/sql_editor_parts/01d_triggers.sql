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
