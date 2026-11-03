/**
 * Cloudflare Pages Function: checks the existing BARÓN Render health endpoint.
 * Same-origin /api/ready avoids browser CORS restrictions.
 */
export async function onRequestGet() {
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store, max-age=0',
    'X-Content-Type-Options': 'nosniff'
  };

  try {
    const upstream = await fetch('https://baroncortinas.onrender.com/health', {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(12000)
    });

    if (upstream.status !== 200 || !(upstream.headers.get('content-type') || '').includes('application/json')) {
      return new Response(JSON.stringify({ ready: false }), { status: 200, headers });
    }

    const body = await upstream.json();
    return new Response(JSON.stringify({ ready: body && body.ok === true }), { status: 200, headers });
  } catch (_) {
    // A sleeping or unavailable Render instance is expected during cold start.
    return new Response(JSON.stringify({ ready: false }), { status: 200, headers });
  }
}
