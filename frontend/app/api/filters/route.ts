import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

export async function GET(request: NextRequest) {
  try {
    const field = request.nextUrl.searchParams.get('field');
    const url = field
      ? `${BACKEND_URL}/api/filters/values?field=${encodeURIComponent(field)}`
      : `${BACKEND_URL}/api/filters`;

    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    const rawBody = await response.text();
    let data: any = {};
    if (rawBody) {
      try {
        data = JSON.parse(rawBody);
      } catch {
        data = { error: rawBody };
      }
    }

    if (!response.ok) {
      return NextResponse.json(
        {
          error: data.error || `Failed to fetch filters (upstream status ${response.status})`,
          upstreamStatus: response.status,
        },
        { status: response.status }
      );
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: 'Failed to fetch filters', details: String(error) }, { status: 500 });
  }
}
