import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

export async function GET(request: NextRequest) {
  try {
    const token = request.nextUrl.searchParams.get('token');
    const format = request.nextUrl.searchParams.get('format') || 'csv';
    const cumulativeSession = request.nextUrl.searchParams.get('cumulative_session');
    const latestOnlyParam = request.nextUrl.searchParams.get('latest_only');
    if (!token) {
      return NextResponse.json({ error: 'Token is required' }, { status: 400 });
    }

    const projectResponse = await fetch(`${BACKEND_URL}/api/projects/${token}`, {
      headers: { Authorization: `Bearer ${BACKEND_API_KEY}`, 'Content-Type': 'application/json' },
      cache: 'no-store',
    });
    const projectData = await projectResponse.json();
    if (!projectResponse.ok || !projectData.data?.id) {
      return NextResponse.json({ error: projectData.error || 'Project not found' }, { status: projectResponse.status || 404 });
    }

    const backendParams = new URLSearchParams({
      format,
      latest_only: latestOnlyParam ?? (cumulativeSession ? '0' : '1'),
    });
    if (cumulativeSession) {
      backendParams.set('project_run_cumulative_id', cumulativeSession);
    }

    const response = await fetch(`${BACKEND_URL}/api/products/${projectData.data.id}/export?${backendParams.toString()}`, {
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({ error: errorText || 'Failed to export data' }, { status: response.status });
    }

    const contentType = response.headers.get('content-type') || (format === 'json' ? 'application/json' : 'text/csv');
    const disposition = response.headers.get('content-disposition') || `attachment; filename="export_${token}.${format}"`;
    const body = await response.text();

    return new NextResponse(body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Disposition': disposition,
      },
    });
  } catch (error) {
    return NextResponse.json({ error: 'Failed to export data', details: String(error) }, { status: 500 });
  }
}
