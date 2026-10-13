import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

export async function GET(request: NextRequest) {
  try {
    const backendUrl = new URL(`${BACKEND_URL}/api/metadata/import-history`);
    request.nextUrl.searchParams.forEach((value, key) => {
      backendUrl.searchParams.set(key, value);
    });

    const response = await fetch(backendUrl.toString(), {
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json({ error: data.error || 'Failed to fetch import history' }, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: 'Failed to fetch import history', details: String(error) }, { status: 500 });
  }
}
