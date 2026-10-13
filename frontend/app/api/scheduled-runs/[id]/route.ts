import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id: rawId } = await params;
    const id = String(rawId || '').trim();
    if (!id) {
      return NextResponse.json({ error: 'Scheduled run id is required' }, { status: 400 });
    }

    const response = await fetch(`${BACKEND_URL}/api/scheduled-runs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json({ error: data.error || 'Failed to delete scheduled run' }, { status: response.status });
    }

    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    return NextResponse.json({ error: 'Failed to delete scheduled run', details: String(error) }, { status: 500 });
  }
}
