import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("lv_token")?.value;
  const { pathname } = request.nextUrl;

  if (pathname === "/login") {
    if (token) return NextResponse.redirect(new URL("/", request.url));
    return NextResponse.next();
  }

  // The Google OAuth landing page carries the fresh session in the URL
  // fragment — by definition there is no cookie yet, so it must be public.
  if (pathname === "/auth/callback") {
    return NextResponse.next();
  }

  if (!token) {
    const url = new URL("/login", request.url);
    url.searchParams.set("from", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
