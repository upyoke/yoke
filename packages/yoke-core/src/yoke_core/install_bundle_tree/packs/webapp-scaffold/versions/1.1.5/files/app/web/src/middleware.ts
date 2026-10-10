import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has("{{project_name}}_session");

  if (hasSession && pathname === "/login") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  if (!hasSession && !PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match all paths except _next, api, and static files
    "/((?!_next|api|favicon\\.ico|.*\\..*).*)",
  ],
};
