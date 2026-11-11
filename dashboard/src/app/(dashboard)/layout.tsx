import Link from "next/link";
import { signOut } from "../login/actions";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="dashboard-shell">
      <nav className="topnav">
        <span className="brand">ARES</span>
        <Link href="/overview">Overview</Link>
        <Link href="/health">Kesehatan sistem</Link>
        <Link href="/watchlist">Watchlist</Link>
        <form action={signOut} className="signout">
          <button type="submit">Keluar</button>
        </form>
      </nav>
      <main className="content">{children}</main>
    </div>
  );
}
