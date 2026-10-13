import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ run_token: string }> }
) {
  try {
    const { run_token } = await params;
    const response = await fetch(`${BACKEND_URL}/api/runs/${run_token}/cancel`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json({ error: data.error || 'Failed to cancel run' }, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: 'Failed to cancel run', details: String(error) }, { status: 500 });
  }
}
