package dev.integratepbr;

public enum MaterialType {
    GENERIC(100, 10, 0), FABRIC(106, 0, 30), LEATHER(110, 0, 0),
    METAL(175, 255, 0), WOOD(145, 0, 12), STONE(85, 0, 12),
    GLASS(220, 12, 0), PLANT(68, 0, 12), LEAVES(124, 0, 223),
    WOOD_METAL(100, 10, 0);

    private final int smoothness, f0, porosity;

    MaterialType(int smoothness, int f0, int porosity) {
        this.smoothness = smoothness;
        this.f0 = f0;
        this.porosity = porosity;
    }

    public int smoothness() { return smoothness; }
    public int f0() { return f0; }
    public int porosity() { return porosity; }
}
