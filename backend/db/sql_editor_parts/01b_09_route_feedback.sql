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
