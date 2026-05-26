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

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'on_auth_user_created_create_profile') then
    create trigger on_auth_user_created_create_profile
    after insert on auth.users
    for each row execute function public.handle_new_user();
  end if;
end $$;
