package dev.integratepbr.texture;

import java.awt.image.BufferedImage;
import java.util.ArrayDeque;

/** Upsamples the source verbatim and bevels only the interior of observed seams. */
public final class SurfaceEnhancer {
    public record Result(BufferedImage albedo, double[][] depth) {}
    private SurfaceEnhancer() {}
    public static boolean candidate(String name, int width, int height, boolean blockTexture) {
        return blockTexture && width>=8 && width<=32 && height==width && TextureStructure.structured(name);
    }
    public static Result enhance(BufferedImage source, String name, boolean blockTexture) {
        int size=source.getWidth();
        if (!candidate(name,size,source.getHeight(),blockTexture)) return null;
        double[][] mask=TextureStructure.depth(source,name,true);
        boolean found=false;
        for (double[] row:mask) for (double value:row) found |= value>0;
        double[][] tonalProbe=new double[size][size];
        SurfaceTone.apply(source,name,tonalProbe);
        for (double[] row:tonalProbe) for (double value:row) found |= value>0;
        if (!found) return null;
        int scale=4, n=size*scale;
        var color=new BufferedImage(n,n,BufferedImage.TYPE_INT_ARGB);
        var distance=new int[n][n]; var queue=new ArrayDeque<Integer>();
        for (int y=0;y<n;y++) for (int x=0;x<n;x++) {
            color.setRGB(x,y,source.getRGB(x/scale,y/scale));
            distance[y][x]=mask[y/scale][x/scale]>0 ? -1 : 0;
            if (distance[y][x]==0) queue.add(y*n+x);
        }
        // Distance to the actual contour, not to every source pixel center. Junctions stay continuous.
        while (!queue.isEmpty()) {
            int index=queue.removeFirst(), x=index%n, y=index/n;
            for (int[] step:TextureStructure.STEPS) {
                int nx=Math.floorMod(x+step[0],n), ny=Math.floorMod(y+step[1],n);
                if (distance[ny][nx]<0) {
                    distance[ny][nx]=distance[y][x]+1; queue.add(ny*n+nx);
                }
            }
        }
        double[][] depth=new double[n][n];
        for (int y=0;y<n;y++) for (int x=0;x<n;x++)
            // One half-height texel forms a narrow straight bevel inside the seam.
            depth[y][x]=distance[y][x]>0 ? Math.min(1,distance[y][x]-.5) * mask[y/scale][x/scale] : 0;
        // Palette stripes are flat, sharply bounded height regions. Only the seam
        // mask above receives a bevel; feeding both through the same distance field
        // rounded every tonal boundary and made engraved motifs look swollen.
        SurfaceTone.apply(color,name,depth);
        return new Result(color,depth);
    }
}
