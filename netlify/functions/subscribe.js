/**
 * Netlify Function: subscribe.js
 * Adds an email to Resend Audience when someone submits the signup form.
 * Auto-fetches the Audience ID — no RESEND_AUDIENCE_ID env var needed.
 *
 * Env vars needed in Netlify dashboard (just these two):
 *   RESEND_API_KEY
 */

async function getAudienceId(apiKey) {
  const res = await fetch("https://api.resend.com/audiences", {
    headers: { "Authorization": `Bearer ${apiKey}` },
  });
  if (!res.ok) throw new Error("Failed to fetch audiences");
  const data = await res.json();
  const audiences = data.data || [];
  if (!audiences.length) throw new Error("No audiences found in Resend account");
  return audiences[0].id;
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ error: "Method not allowed" }) };
  }

  let email;
  try {
    ({ email } = JSON.parse(event.body));
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid request body" }) };
  }

  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!email || !emailRe.test(email)) {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid email address" }) };
  }

  const RESEND_API_KEY = process.env.RESEND_API_KEY;
  if (!RESEND_API_KEY) {
    console.error("Missing RESEND_API_KEY env var");
    return { statusCode: 500, body: JSON.stringify({ error: "Server misconfiguration" }) };
  }

  try {
    const audienceId = await getAudienceId(RESEND_API_KEY);

    const res = await fetch(
      `https://api.resend.com/audiences/${audienceId}/contacts`,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${RESEND_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, unsubscribed: false }),
      }
    );

    if (res.status === 409) {
      return { statusCode: 200, body: JSON.stringify({ ok: true }) };
    }

    if (!res.ok) {
      const err = await res.json();
      console.error("Resend error:", err);
      return { statusCode: 500, body: JSON.stringify({ error: "Failed to subscribe. Please try again." }) };
    }

    return { statusCode: 200, body: JSON.stringify({ ok: true }) };
  } catch (err) {
    console.error("Error:", err.message);
    return { statusCode: 500, body: JSON.stringify({ error: "Something went wrong. Please try again." }) };
  }
};
