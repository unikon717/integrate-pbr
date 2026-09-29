package dev.integratepbr;

import java.awt.image.BufferedImage;
import java.util.ArrayDeque;
import java.util.Locale;

/** Local, rotation-symmetric seam evidence. Never extrapolates a detected line. */
final class TextureStructure {
    private TextureStructure() {}
    static final int[][] STEPS = {{-1,0},{1,0},{0,-1},{0,1}};

    static double[][] depth(BufferedImage source, String name, boolean blockTexture) {
        int w = source.getWidth(), h = source.getHeight();
        double[][] result = new double[h][w], light = new double[h][w];
        if (!blockTexture || w < 8 || h < 8 || !structured(name)) return result;
        double low = 255, high = 0;
        int[] histogram = new int[256];
        for (int y=0; y<h; y++) for (int x=0; x<w; x++) {
            int c = source.getRGB(x,y);
            if ((c >>> 24) != 255) return result;
            double v = (c >>> 16 & 255)*.2126 + (c >>> 8 & 255)*.7152 + (c & 255)*.0722;
            histogram[(int)Math.round(v)]++;
            light[y][x]=v; low=Math.min(low,v); high=Math.max(high,v);
        }
        if (high-low < 10) return result;
        boolean[][] candidate = new boolean[h][w], visited = new boolean[h][w];
        // Robust contrast range: a few bright bark flecks must not hide the interior rings.
        int cumulative=0, p20=0, p80=255;
        for (int i=0;i<256;i++) {
            cumulative+=histogram[i];
            if (cumulative<w*h*.2) p20=i;
            if (cumulative>=w*h*.8) { p80=i; break; }
        }
        double threshold = Math.max(4, (p80-p20)*.16);
        for (int y=0; y<h; y++) for (int x=0; x<w; x++) {
            double c=light[y][x];
            // A dark ridge must have brighter faces on BOTH sides. A single color edge is not a groove.
            double across = Math.min(light[y][Math.floorMod(x-1,w)],light[y][(x+1)%w])-c;
            double along = Math.min(light[Math.floorMod(y-1,h)][x],light[(y+1)%h][x])-c;
            candidate[y][x] = Math.max(across,along) >= threshold;
        }
        // Recover observed right-angle corners using diagonal ridge evidence plus two
        // existing orthogonal segments. Never bridge a bright gap in a broken contour.
        boolean[][] corners = new boolean[h][w];
        for (int y=0;y<h;y++) for (int x=0;x<w;x++) {
            int l=Math.floorMod(x-1,w), r=(x+1)%w, u=Math.floorMod(y-1,h), d=(y+1)%h;
            boolean horizontal=candidate[y][l] || candidate[y][r];
            boolean vertical=candidate[u][x] || candidate[d][x];
            double diagonal=Math.max(Math.min(light[u][l],light[d][r]),
                    Math.min(light[u][r],light[d][l]))-light[y][x];
            corners[y][x]=horizontal && vertical && diagonal>=threshold;
        }
        for (int y=0;y<h;y++) for (int x=0;x<w;x++) candidate[y][x] |= corners[y][x];
        // A speckle must not borrow confidence merely by touching a long seam.
        boolean[][] supported = new boolean[h][w];
        double[][] confidence = new double[h][w];
        int minimumRun = Math.max(4, Math.min(8, (Math.min(w,h)+7)/8));
        for (int y=0;y<h;y++) for (int x=0;x<w;x++) {
            if (!candidate[y][x]) continue;
            int run = Math.max(runLength(candidate,x,y,1,0,minimumRun+2),
                    runLength(candidate,x,y,0,1,minimumRun+2));
            supported[y][x] = run >= minimumRun;
            confidence[y][x] = Math.min(1, .6 + .2*(run-minimumRun));
        }
        // Recover only observed corners between supported segments, never dangling spurs.
        for (int y=0;y<h;y++) for (int x=0;x<w;x++) {
            if (!candidate[y][x] || supported[y][x]) { corners[y][x]=false; continue; }
            boolean horizontal=supported[y][Math.floorMod(x-1,w)] || supported[y][(x+1)%w];
            boolean vertical=supported[Math.floorMod(y-1,h)][x] || supported[(y+1)%h][x];
            corners[y][x]=horizontal && vertical && corners[y][x];
        }
        for (int y=0;y<h;y++) for (int x=0;x<w;x++) {
            candidate[y][x]=supported[y][x] || corners[y][x];
            if (!supported[y][x]) confidence[y][x]=.6;
        }
        // Require a connected contour, rejecting isolated texture speckles. All visits are O(pixels).
        int marked=0;
        for (int y=0; y<h; y++) for (int x=0; x<w; x++) {
            if (!candidate[y][x] || visited[y][x]) continue;
            var queue=new ArrayDeque<Integer>(); var component=new ArrayDeque<Integer>();
            queue.add(y*w+x); visited[y][x]=true;
            while (!queue.isEmpty()) {
                int index=queue.removeFirst(); component.add(index);
                int cy=index/w, cx=index%w;
                for (int[] step:STEPS) {
                    int nx=Math.floorMod(cx+step[0],w), ny=Math.floorMod(cy+step[1],h);
                    if (candidate[ny][nx] && !visited[ny][nx]) {
                        visited[ny][nx]=true; queue.add(ny*w+nx);
                    }
                }
            }
            if (component.size()<3) continue;
            for (int index:component) result[index/w][index%w]=confidence[index/w][index%w];
            marked+=component.size();
        }
        // Dense alternating colors are ambiguous, not evidence for a corrugated surface.
        if (marked > w*h*.4) return new double[h][w];
        return result;
    }

    /** Bounded directional support, including texture tile boundaries. */
    private static int runLength(boolean[][] mask,int x,int y,int dx,int dy,int cap) {
        int h=mask.length,w=mask[0].length,count=1;
        int limit=Math.min(cap,dx==0?h:w);
        for (int sign:new int[]{-1,1}) {
            for (int step=1;step<limit && count<limit;step++) {
                int nx=Math.floorMod(x+sign*dx*step,w),ny=Math.floorMod(y+sign*dy*step,h);
                if (!mask[ny][nx]) break;
                count++;
            }
        }
        return count;
    }

    static boolean structured(String name) {
        return has(name,"plank","planks","log","stem","bark","brick","bricks","tile","tiles");
    }
    static boolean has(String name, String... terms) {
        String words="_"+name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+","_")+"_";
        for (String term:terms) if (words.contains("_"+term+"_")) return true;
        return false;
    }
}
