import { NextResponse, type NextRequest } from "next/server";

// Session cookie names set by the API: "__Host-" over HTTPS, the plain name
// only where SESSION_COOKIE_SECURE is off (local development).
const SESSION_COOKIES = ["__Host-op_session", "op_session"];
const PUBLIC_PATHS = ["/login", "/setup-password"];

/**
 * Sends visitors without a session cookie to the sign-in page. This is only a
 * convenience: whether the session is valid, and what the user may see or do,
 * is decided by the API on every request.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }
  if (SESSION_COOKIES.some((name) => request.cookies.has(name))) return NextResponse.next();
  const login = new URL("/login", request.url);
  if (pathname !== "/") login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:png|svg|ico|jpg|jpeg|webp)$).*)"],
};
