const UPSTREAM_URL =
  "https://raw.githubusercontent.com/akrenev-droid/prod_calendar/main/ru-production-calendar.ics";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (
      url.pathname !== "/" &&
      url.pathname !== "/calendar.ics" &&
      url.pathname !== "/ru-production-calendar.ics"
    ) {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    const upstream = await fetch(UPSTREAM_URL, {
      headers: { "User-Agent": "ru-prod-calendar-worker/1.0" },
      cf: { cacheEverything: true, cacheTtl: 600 },
    });

    if (!upstream.ok || !upstream.body) {
      return new Response("Calendar temporarily unavailable", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": 'inline; filename="ru-production-calendar.ics"',
        "Cache-Control": "public, max-age=600",
        "Access-Control-Allow-Origin": "*",
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
};
