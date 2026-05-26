select
  to_regclass('public.profiles') as profiles,
  to_regclass('public.board_templates') as board_templates,
  to_regclass('public.hold_assets') as hold_assets,
  to_regclass('public.board_assets') as board_assets,
  to_regclass('public.route_holds') as route_holds,
  to_regclass('public.route_beta_steps') as route_beta_steps,
  to_regclass('public.ai_generation_tasks') as ai_generation_tasks,
  to_regclass('public.route_review_findings') as route_review_findings,
  to_regclass('public.route_feedback') as route_feedback,
  to_regclass('public.route_learning_patterns') as route_learning_patterns,
  to_regclass('public.modification_logs') as modification_logs;
