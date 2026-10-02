package dev.integratepbr.texture;

import java.awt.image.BufferedImage;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Map;
import java.util.TreeSet;

/** Shallow relief for coherent palette regions, independently of narrow seam detection. */
final class SurfaceTone {
    private SurfaceTone() {}

    static void apply(BufferedImage image,String name,double[][] depth) {
        if (!TextureStructure.has(name,"stripped","plank","planks","brick","bricks",
                "tile","tiles","door","trapdoor")) return;
        int w=image.getWidth(),h=image.getHeight();
        var counts=new HashMap<Integer,Integer>();
        for(int y=0;y<h;y++) for(int x=0;x<w;x++) {
            int c=image.getRGB(x,y);
            if((c>>>24)==255 && !TextureStructure.mossPixel(c,name)) counts.merge(c,1,Integer::sum);
        }
        // Deterministic modal source color anchors the unchanged broad surface.
        int base=0,best=0;
        for(var entry:counts.entrySet()) if(entry.getValue()>best
                || entry.getValue()==best && light(entry.getKey())>light(base)) {
            base=entry.getKey();best=entry.getValue();
        }
        if(best==0) return;
        double baseLight=light(base),range=0;
        for(int c:counts.keySet()) if(compatible(c,base)) {
            double delta=baseLight-light(c);
            if(delta>0 && delta<=baseLight*.25) range=Math.max(range,delta);
        }
        if(range<2) return;
        boolean shallow=TextureStructure.has(name,"stripped","door","trapdoor");
        boolean strippedLog=TextureStructure.has(name,"stripped")
                && TextureStructure.has(name,"log","stem","bark");
        boolean masonry=TextureStructure.has(name,"brick","bricks","stonebrick","stonebricks",
                "tile","tiles");
        boolean doorPanel=TextureStructure.has(name,"door","trapdoor");
        boolean continuous=shallow && !doorPanel;
        var palette=new TreeSet<Integer>();
        if(continuous) for(var entry:counts.entrySet()) {
            int c=entry.getKey();
            double delta=baseLight-light(c);
            if(entry.getValue()>=2 && compatible(c,base) && delta>=Math.max(1,range*.12)
                    && delta<=baseLight*.25) palette.add((int)Math.round(delta));
        }
        Map<Integer,Integer> levels=new HashMap<>();
        if(continuous) {
            int rank=0;
            for(int delta:palette) levels.put(delta,Math.min(8,++rank));
        }
        int[][] bands=new int[h][w];
        for(int y=0;y<h;y++) for(int x=0;x<w;x++) {
            int c=image.getRGB(x,y);
            double delta=baseLight-light(c);
            if((c>>>24)!=255 || !compatible(c,base) || TextureStructure.mossPixel(c,name)
                    || delta<Math.max(1,range*.12) || delta>baseLight*.25) continue;
            if(continuous) bands[y][x]=levels.getOrDefault((int)Math.round(delta),0);
            else bands[y][x]=delta>=range*.5 ? 2 : 1;
        }
        boolean[][] seen=new boolean[h][w];
        for(int y=0;y<h;y++) for(int x=0;x<w;x++) {
            if(seen[y][x] || bands[y][x]==0) continue;
            int band=bands[y][x];
            var queue=new ArrayDeque<Integer>();var component=new ArrayDeque<Integer>();
            queue.add(y*w+x);seen[y][x]=true;
            while(!queue.isEmpty()) {
                int p=queue.removeFirst(),px=p%w,py=p/w;component.add(p);
                for(int[] step:TextureStructure.STEPS) {
                    int nx=px+step[0],ny=py+step[1];
                    if(nx<0 || ny<0 || nx>=w || ny>=h || seen[ny][nx] || bands[ny][nx]!=band) continue;
                    seen[ny][nx]=true;queue.add(ny*w+nx);
                }
            }
            if(component.size()<4) continue;
            // Keep tonal steps within each material's absolute height budget:
            // stripped-log tones step by 1 up to 8; doors step by 3 up to 24.
            // Masonry gets two surface layers at 2 alpha units per step. Door panels
            // stay within 2 units total; structural seams are handled separately.
            double value=continuous ? (band*(strippedLog ? 1.0 : 3.0))/(strippedLog ? 8 : 24)
                    : masonry ? band*2.0/48 : doorPanel ? band*1.0/24
                    : (band==2 ? .5 : .3)*(shallow ? 2 : 1);
            for(int p:component) {
                int px=p%w,py=p/w;
                if(depth[py][px]==0) depth[py][px]=value;
            }
        }
    }

    private static double light(int c) {
        return (c>>>16&255)*.2126+(c>>>8&255)*.7152+(c&255)*.0722;
    }
    private static boolean compatible(int a,int b) {
        double sumA=(a>>>16&255)+(a>>>8&255)+(a&255);
        double sumB=(b>>>16&255)+(b>>>8&255)+(b&255);
        if(sumA==0 || sumB==0) return false;
        return Math.abs((a>>>16&255)/sumA-(b>>>16&255)/sumB)<.08
                && Math.abs((a>>>8&255)/sumA-(b>>>8&255)/sumB)<.08;
    }
}
