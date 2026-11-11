import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

// Per-request Supabase client bound to the signed-in user's session cookies.
// Uses the anon/publishable key only — the dashboard never holds the
// service_role key, so every query here is subject to Postgres RLS.
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options);
            }
          } catch {
            // Called from a Server Component render — ignore, the proxy
            // (src/proxy.ts) already refreshes the session on every request.
          }
        },
      },
    },
  );
}
