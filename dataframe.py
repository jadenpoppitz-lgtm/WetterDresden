import pandas as pd
import matplotlib.pyplot as plt


def read_file(file):
    df = pd.read_csv(file, sep = ';')

    bf = df[['Datum','tägliche Niederschlagshöhe', 'Tagesmittel der Temperatur']].copy()
    
    bf = bf.rename(columns= {
        'Datum': 'Date',
        'tägliche Niederschlagshöhe': 'Rain',
        'Tagesmittel der Temperatur': 'Temp'  
    })

    bf['Date'] = pd.to_datetime(bf['Date'], format='%Y%m%d')
    bf['Year'] = bf['Date'].dt.year
    
    bf['Temp'] = pd.to_numeric(bf['Temp'].astype(str).str.replace(',', '.'), errors='coerce')
    bf['Rain'] = pd.to_numeric(bf['Rain'].astype(str).str.replace(',', '.'), errors='coerce')

    return bf

def year_bound(df, begin, end):
    df = df[(df['Year'] >= int(begin)) & (df['Year'] <= int(end))]

    yearly_temp = df.groupby('Year')['Temp'].mean()
    yearly_rain = df.groupby('Year')['Rain'].mean()

    return yearly_temp, yearly_rain

def graph(yearly_temp):
    plt.figure(figsize = (12,6))
    plt.plot(yearly_temp.index, yearly_temp.values)
    plt.title('Durchschnittliche Jahrestemperatur')
    plt.xlabel('Jahr')
    plt.ylabel('Temperatur in °C')
    plt.show()
    