import { NextRequest, NextResponse } from "next/server";

const REALM = "Artist Growth OS";
const MIN_PASSWORD_LENGTH = 24;

function challenge(): NextResponse {
  return new NextResponse("Operator authentication required.", {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
    },
  });
}

function unavailable(): NextResponse {
  return new NextResponse("Web operator authentication is not configured.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
}

async function digest(value: string): Promise<Uint8Array> {
  const bytes = new TextEncoder().encode(value);
  return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
}

async function secureEqual(left: string, right: string): Promise<boolean> {
  const [leftDigest, rightDigest] = await Promise.all([digest(left), digest(right)]);
  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest[index] ^ rightDigest[index];
  }
  return difference === 0;
}

function parseBasicAuthorization(header: string | null): { username: string; password: string } | null {
  if (!header?.startsWith("Basic ")) return null;

  try {
    const decoded = atob(header.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 1) return null;
    return {
      username: decoded.slice(0, separator),
      password: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
}

export async function proxy(request: NextRequest) {
  const expectedUsername = process.env.WEB_OPERATOR_USERNAME;
  const expectedPassword = process.env.WEB_OPERATOR_PASSWORD;

  if (
    !expectedUsername ||
    !expectedPassword ||
    expectedPassword.length < MIN_PASSWORD_LENGTH
  ) {
    return unavailable();
  }

  const supplied = parseBasicAuthorization(request.headers.get("authorization"));
  if (!supplied) return challenge();

  const [usernameMatches, passwordMatches] = await Promise.all([
    secureEqual(supplied.username, expectedUsername),
    secureEqual(supplied.password, expectedPassword),
  ]);

  if (!usernameMatches || !passwordMatches) return challenge();

  const response = NextResponse.next();
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
