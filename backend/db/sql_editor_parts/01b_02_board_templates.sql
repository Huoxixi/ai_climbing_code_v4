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
