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
