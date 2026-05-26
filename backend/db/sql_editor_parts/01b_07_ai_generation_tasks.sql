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
