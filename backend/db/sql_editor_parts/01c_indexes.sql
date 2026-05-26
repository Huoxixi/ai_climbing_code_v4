create unique index if not exists hold_assets_owner_variant_idx on public.hold_assets(owner_id, hold_type, variant) where owner_id is not null and archived_at is null;
create unique index if not exists hold_assets_system_variant_idx on public.hold_assets(hold_type, variant) where owner_id is null and archived_at is null;
create index if not exists board_assets_owner_updated_idx on public.board_assets(owner_id, updated_at desc) where archived_at is null;
create index if not exists board_assets_visibility_idx on public.board_assets(visibility) where archived_at is null;
create index if not exists route_holds_board_idx on public.route_holds(board_asset_id, sort_order);
create index if not exists route_beta_steps_board_idx on public.route_beta_steps(board_asset_id, step_index);
create index if not exists hold_assets_lookup_idx on public.hold_assets(hold_type, variant) where archived_at is null;
create index if not exists ai_generation_tasks_owner_created_idx on public.ai_generation_tasks(owner_id, created_at desc);
