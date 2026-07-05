from dataframe import read_file, summarize_period, year_bound


def main():
    print("Willkommen zur Wetterdatenanalyse Dresden-Klotzsche")
    begin = int(input("Jahr Beginn: "))
    end = int(input("Jahr Ende: "))

    df = read_file()
    result = summarize_period(df, begin, end)
    yearly_temp, yearly_rain = year_bound(df, begin, end)

    print("\nKennzahlen")
    print(f"Tage: {result['days']}")
    print(f"Temperaturmittel: {result['temp_avg_c']:.1f} °C")
    print(f"Temperaturmaximum: {result['temp_max_c']:.1f} °C")
    print(f"Temperaturminimum: {result['temp_min_c']:.1f} °C")
    print(f"Niederschlag gesamt: {result['rain_sum_mm']:.1f} mm")
    print(f"Regentage: {result['wet_days']}")

    print("\nJahreswerte")
    for year in yearly_temp.index:
        print(
            f"{year}: {yearly_temp.loc[year]:.1f} °C, "
            f"{yearly_rain.loc[year]:.1f} mm Niederschlag"
        )


if __name__ == "__main__":
    main()
