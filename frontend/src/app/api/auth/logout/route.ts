import { getSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST() {
  const session = await getSession();
  session.destroy(); // clears the cookie; stateless, so nothing to revoke
  return Response.json({ ok: true });
}
