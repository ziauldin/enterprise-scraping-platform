import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const response = await fetch(`${BACKEND_URL}/api/projects/sync-msa`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
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
          error: data.error || `Failed to sync MSA projects (upstream status ${response.status})`,
          upstreamStatus: response.status,
        },
        { status: response.status }
      );
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: 'Failed to sync MSA projects', details: String(error) }, { status: 500 });
  }
}
