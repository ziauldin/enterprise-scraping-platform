import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

async function parseUpstreamResponse(response: Response) {
  const rawBody = await response.text();
  if (!rawBody) {
    return {};
  }

  try {
    return JSON.parse(rawBody);
  } catch {
    return { error: rawBody };
  }
}

export async function GET(request: NextRequest) {
  try {
    const token = request.nextUrl.searchParams.get('token');
    const requestedLimit = request.nextUrl.searchParams.get('limit') || '1000';
    const cumulativeSession = request.nextUrl.searchParams.get('cumulative_session');
    const latestOnlyParam = request.nextUrl.searchParams.get('latest_only');
    if (!token) {
      return NextResponse.json({ error: 'Token is required' }, { status: 400 });
    }

    const parsedLimit = requestedLimit.toLowerCase() === 'all' ? 5000 : Number.parseInt(requestedLimit, 10);
    const safeLimit = Number.isFinite(parsedLimit) ? Math.min(Math.max(parsedLimit, 1), 5000) : 1000;

    const headers = {
      Authorization: `Bearer ${BACKEND_API_KEY}`,
      'Content-Type': 'application/json',
    };

    const projectResponse = await fetch(`${BACKEND_URL}/api/projects/${token}`, {
      headers,
      cache: 'no-store',
    });
    const projectData = await parseUpstreamResponse(projectResponse);
    if (!projectResponse.ok || !projectData.data?.id) {
      return NextResponse.json(
        {
          error: projectData.error || `Failed to fetch project (upstream status ${projectResponse.status})`,
          upstreamStatus: projectResponse.status,
        },
        { status: projectResponse.status || 404 }
      );
    }

    const latestOnly = latestOnlyParam ?? (cumulativeSession ? '0' : '1');
    const backendParams = new URLSearchParams({
      limit: String(safeLimit),
      latest_only: latestOnly,
    });
    if (cumulativeSession) {
      backendParams.set('project_run_cumulative_id', cumulativeSession);
    }

    const backendDataResponse = await fetch(`${BACKEND_URL}/api/products/${projectData.data.id}?${backendParams.toString()}`, {
      headers,
      cache: 'no-store',
    });

    const backendData = await parseUpstreamResponse(backendDataResponse);
    if (!backendDataResponse.ok) {
      return NextResponse.json(
        {
          error: backendData.error || `Failed to fetch data (upstream status ${backendDataResponse.status})`,
          upstreamStatus: backendDataResponse.status,
        },
        { status: backendDataResponse.status }
      );
    }

    return NextResponse.json({
      success: true,
      count: backendData.count || 0,
      data: backendData.data || [],
      limit: safeLimit,
      current_cumulative_session: backendData.current_cumulative_session || null,
    });
  } catch (error) {
    return NextResponse.json({ error: 'Failed to fetch data', details: String(error) }, { status: 500 });
  }
}
