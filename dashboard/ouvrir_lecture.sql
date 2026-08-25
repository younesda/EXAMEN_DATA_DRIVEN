-- SQL Editor Supabase → Run
-- Ouvre la lecture des tables pour le dashboard.

grant usage on schema public to anon, authenticated;
grant select on all tables in schema public to anon, authenticated;

do $$
declare t text;
begin
  foreach t in array array[
    'dim_produit','dim_client','dim_date','dim_promotion',
    'fact_ventes','fact_evenements_web','fact_stock'
  ]
  loop
    execute format('alter table public.%I enable row level security', t);
    begin
      execute format(
        'create policy lecture_dash on public.%I for select to anon, authenticated using (true)',
        t
      );
    exception when duplicate_object then
      null;
    end;
  end loop;
end $$;
