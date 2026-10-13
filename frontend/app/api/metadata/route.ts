import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const API_KEY = process.env.BACKEND_API_KEY ?? '';
const REQUEST_TIMEOUT = 30000; // 30 seconds timeout

/**
 * GET /api/metadata
 * Fetches metadata records with optional filtering
 * Proxies to Flask backend: GET /api/metadata
 */
export async function GET(request: NextRequest) {
  try {
    // Extract query parameters
    const searchParams = request.nextUrl.searchParams;
    const projectToken = searchParams.get('project_token');
    const region = searchParams.get('region');
    const country = searchParams.get('country');
    const brand = searchParams.get('brand');
    const search = searchParams.get('search');
    const limit = searchParams.get('limit') || '100';
    const offset = searchParams.get('offset') || '0';

    // Build backend URL
    const params = new URLSearchParams();
    if (projectToken) params.append('project_token', projectToken);
    if (region) params.append('region', region);
    if (country) params.append('country', country);
    if (brand) params.append('brand', brand);
    if (search) params.append('search', search);
    params.append('limit', limit);
    params.append('offset', offset);

    const backendUrl = `${BACKEND_URL}/api/metadata?${params.toString()}`;

    console.log(`[API] GET /api/metadata - Proxying to: ${backendUrl}`);

    // Call Flask backend with timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    
    try {
      const response = await fetch(backendUrl, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json',
        },
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      
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
        console.error(`[API] Backend returned ${response.status}:`, data);
        return NextResponse.json(
          {
            error: data.error || `Failed to fetch metadata (upstream status ${response.status})`,
            upstreamStatus: response.status,
          },
          { status: response.status }
        );
      }

      console.log(`[API] Successfully fetched ${data.count} metadata records`);
      return NextResponse.json(data, { status: 200 });
    } finally {
      clearTimeout(timeoutId);
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      console.error('[API] Metadata request timeout (30s exceeded)');
      return NextResponse.json(
        { error: 'Metadata request timeout' },
        { status: 504 }
      );
    }
    console.error('[API] Error fetching metadata:', error);
    return NextResponse.json(
      { error: 'Failed to fetch metadata', details: String(error) },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

    try {
      const response = await fetch(`${BACKEND_URL}/api/metadata`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
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
            error: data.error || `Failed to create metadata record (upstream status ${response.status})`,
            upstreamStatus: response.status,
          },
          { status: response.status }
        );
      }

      return NextResponse.json(data, { status: 201 });
    } finally {
      clearTimeout(timeoutId);
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json({ error: 'Metadata create request timeout' }, { status: 504 });
    }
    return NextResponse.json(
      { error: 'Failed to create metadata record', details: String(error) },
      { status: 500 }
    );
  }
}
